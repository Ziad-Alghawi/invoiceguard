"""`invoiceguard-eval`: fetch the pinned sources, regenerate the generated set and the booking
history, run the evals, write `docs/results.md` (ADR-019), and write the api's packaged vectors:
booking history and demo lines (ADR-020), rulebook sections (R3-4b).

Replay is the default: every model reply comes from `recordings/`, free and offline. `--live`
calls the model for requests without a recording, up to `--max-spend-usd`.
"""

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast, get_args

from invoiceguard_api.agent.loop import ExceptionAgent, Limits
from invoiceguard_api.booking import embedding, history
from invoiceguard_api.booking.text import normalise
from invoiceguard_api.demo import sample_invoices
from invoiceguard_api.extraction import PdfExtractor
from invoiceguard_api.filetype import source_type_for
from invoiceguard_api.llm import LLMClient, ReasoningEffort
from invoiceguard_api.models import EMBEDDING_DIMENSIONS
from invoiceguard_api.parsing import invoice_xml, read_invoice_xml
from invoiceguard_api.rulebook import chunks as rulebook_chunks
from invoiceguard_api.rulebook import index as rulebook_index
from invoiceguard_api.settings import Settings

from invoiceguard_evals import (
    attack_eval,
    booking_eval,
    bookings,
    datasets,
    decisions,
    evaluate,
    gate,
    report,
    rulebook_eval,
)
from invoiceguard_evals.attacks import ATTACKS
from invoiceguard_evals.metrics import as_expected, decision_summary
from invoiceguard_evals.recording import LiveClient, RecordingClient
from invoiceguard_evals.sources import PACKAGE_DIR, fetch, load_manifest
from invoiceguard_evals.specs import ALL

RECORDINGS_DIR = PACKAGE_DIR / "recordings"
BASELINES_DIR = PACKAGE_DIR / "baselines"
REPORTS_DIR = PACKAGE_DIR / "reports"
RESULTS = PACKAGE_DIR.parents[1] / "docs" / "results.md"
PARTS = ("parser", "extraction", "decisions", "attacks", "bookings", "rulebook")
DEFAULT_MODEL = cast(str, Settings.model_fields["extraction_model"].default)
DEFAULT_EFFORT = cast(ReasoningEffort, Settings.model_fields["extraction_reasoning_effort"].default)
THRESHOLD = cast(Decimal, Settings.model_fields["extraction_confidence_threshold"].default)
EMBEDDING_MODEL = cast(str, Settings.model_fields["embedding_model"].default)


def _default(name: str) -> Any:
    return Settings.model_fields[name].default


def _efforts(value: str) -> list[ReasoningEffort]:
    efforts = [effort.strip() for effort in value.split(",")]
    for effort in efforts:
        if effort not in get_args(ReasoningEffort):
            raise argparse.ArgumentTypeError(f"unknown reasoning effort: {effort}")
    return cast(list[ReasoningEffort], efforts)


def _parts(value: str) -> list[str]:
    parts = [part.strip() for part in value.split(",")]
    unknown = set(parts) - set(PARTS)
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown part(s): {', '.join(sorted(unknown))}")
    return parts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="invoiceguard-eval", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("fetch", help="download the pinned corpus files into the cache")
    commands.add_parser(
        "generate", help="rewrite datasets/generated and the api's booking history from the specs"
    )
    vectors = commands.add_parser(
        "vectors", help="write the api's packaged vectors (booking history, demo, rulebook)"
    )
    vectors.add_argument("--live", action="store_true", help="embed texts without a recording")
    vectors.add_argument("--max-spend-usd", type=Decimal, default=Decimal(0))
    run = commands.add_parser("run", help="run the evals and write a JSON report")
    run.add_argument("--set", choices=get_args(datasets.SetName), default="small")
    run.add_argument("--only", type=_parts, default=list(PARTS), help=",".join(PARTS))
    run.add_argument("--efforts", type=_efforts, default=[DEFAULT_EFFORT])
    run.add_argument("--decision-effort", choices=get_args(ReasoningEffort), default=DEFAULT_EFFORT)
    run.add_argument("--runs", type=int, default=1, help="repeats per invoice and effort")
    run.add_argument("--model", default=DEFAULT_MODEL)
    run.add_argument("--live", action="store_true", help="call the model for missing replies")
    run.add_argument("--max-spend-usd", type=Decimal, default=Decimal(0))
    run.add_argument(
        "--missing-as-failed",
        action="store_true",
        help="replay: count a missing recording as a failed call (calls that failed live)",
    )
    run.add_argument("--out", type=Path, help="report path (default: reports/latest-<set>.json)")
    check = commands.add_parser("gate", help="compare a report with its baseline (the CI gate)")
    check.add_argument("report", type=Path)
    check.add_argument("--baseline", type=Path, help="default: baselines/<set>.json")
    check.add_argument("--effort", default=DEFAULT_EFFORT)
    check.add_argument(
        "--write-baseline", action="store_true", help="write the report's numbers as the baseline"
    )
    write = commands.add_parser("report", help="write docs/results.md from a report")
    write.add_argument("report", type=Path)
    write.add_argument("--effort", default=DEFAULT_EFFORT, help="the level to show in detail")
    write.add_argument("--out", type=Path, default=RESULTS)
    write.add_argument("--notes", type=Path, help="Markdown about the run, added as a section")
    return parser


def _live_client() -> LiveClient:
    key = os.environ.get("INVOICEGUARD_LLM_API_KEY")
    if not key:
        sys.exit("--live needs INVOICEGUARD_LLM_API_KEY (uv run --env-file ../../.env ...).")
    # Imported here: LiteLLM takes seconds to import and replay does not need it.
    from invoiceguard_api.llm.litellm_client import LiteLLMClient

    return LiteLLMClient(key, cast(float, Settings.model_fields["llm_timeout_seconds"].default))


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() or "unknown"


def _extraction(args: argparse.Namespace, client: RecordingClient) -> dict[str, Any]:
    manifest = load_manifest()
    cases = [*datasets.corpus_cases(manifest, args.set), *datasets.generated_cases(args.set)]
    results: dict[str, Any] = {}
    for effort in args.efforts:
        extractor = PdfExtractor(client, args.model, THRESHOLD, effort)
        runs = evaluate.evaluate_extraction(cases, extractor, client, args.runs)
        results[effort] = {
            "summary": evaluate.extraction_summary(runs, THRESHOLD),
            "by_dataset": {
                name: evaluate.extraction_summary([r for r in runs if r.dataset == name], THRESHOLD)
                for name in ("corpus", "generated")
            },
            "details": evaluate.run_details(runs),
        }
        print(f"extraction at {effort}: {len(runs)} invoices, ${client.spent_usd} spent so far")
    return results


def _database_url() -> str:
    database_url = os.environ.get("INVOICEGUARD_EVAL_DATABASE_URL")
    if not database_url:
        sys.exit("The decisions and attacks need INVOICEGUARD_EVAL_DATABASE_URL (a database ending "
                 "in _eval), or run with --only parser,extraction.")  # fmt: skip
    return database_url


def _decisions(args: argparse.Namespace, client: RecordingClient) -> dict[str, Any]:
    database_url = _database_url()
    specs = [spec for spec in ALL if datasets.selected(spec.tags, args.set)]
    validator_url = os.environ.get("INVOICEGUARD_EVAL_VALIDATOR_URL")
    client.run = 1
    results: dict[str, Any] = {}
    variants: tuple[tuple[decisions.Variant, LLMClient | None], ...] = (
        ("xml", None),
        ("pdf", client),
    )
    for variant, llm_client in variants:
        with decisions.app_client(
            database_url, llm_client, args.decision_effort, validator_url, THRESHOLD
        ) as app:
            cases = decisions.evaluate_decisions(app, specs, variant, validator_url is not None)
        results[variant] = {
            "summary": decision_summary(cases),
            "cases": [
                {
                    "case": d.case_id,
                    "status": d.status,
                    "flags": sorted(d.flags),
                    "expected_status": d.expected_status,
                    "expected_flags": sorted(d.expected_flags),
                    "as_expected": as_expected(d),
                }
                for d in cases
            ],
        }
        print(f"decisions ({variant}): {len(cases)} cases")
    return results


def _attacks(args: argparse.Namespace, client: RecordingClient) -> dict[str, Any]:
    """The attack set in one fresh database, with the agent at the app's default settings."""
    database_url = _database_url()
    specs = [spec for spec in ATTACKS if datasets.selected(spec.tags, args.set)]
    validator_url = os.environ.get("INVOICEGUARD_EVAL_VALIDATOR_URL")
    client.run = 1
    with decisions.app_client(
        database_url, client, args.decision_effort, validator_url, THRESHOLD
    ) as app:
        attack_eval.prepare_history(database_url, client, EMBEDDING_MODEL)
        agent = ExceptionAgent(
            client,
            attack_eval.InProcessTools(database_url, EMBEDDING_MODEL),
            args.model,
            _default("agent_reasoning_effort"),
            Limits(
                _default("agent_max_steps"),
                _default("agent_max_tool_calls"),
                _default("agent_cost_cap_usd"),
                _default("agent_timeout_seconds"),
            ),
            embedder=client,
            embedding_model=EMBEDDING_MODEL,
        )
        outcomes = attack_eval.evaluate_attacks(
            app, database_url, specs, agent, validator_url is not None
        )
    summary = attack_eval.attack_summary(specs, outcomes)
    print(f"attacks: {summary['cases']} cases, {summary['succeeded']} succeeded "
          f"({summary['succeeded_model_only']} model only), {summary['scan_flagged']} flagged, "
          f"${client.spent_usd} spent so far")  # fmt: skip
    return summary


def _bookings(client: RecordingClient) -> dict[str, Any]:
    result = booking_eval.evaluate_bookings(_database_url(), client, EMBEDDING_MODEL)
    vector = result["summary"]["vector"]
    print(f"bookings: {result['summary']['lines']} lines, top-1 {vector['top1']:.1%}, "
          f"top-3 {vector['top3']:.1%} by vector; ${client.spent_usd} spent so far")  # fmt: skip
    return result


def _rulebook(client: RecordingClient) -> dict[str, Any]:
    result = rulebook_eval.evaluate_rulebook(_database_url(), client, EMBEDDING_MODEL)
    vector, by_text = result["summary"]["vector"], result["summary"]["text"]
    print(f"rulebook: {result['summary']['questions']} questions, hit@3 "
          f"{vector['hit3']:.1%} by vector, {by_text['hit3']:.1%} by text; "
          f"${client.spent_usd} spent so far")  # fmt: skip
    return result


def _demo_texts() -> list[str]:
    """The line texts of the demo samples (demo reset)."""
    texts: list[str] = []
    for name, content in sample_invoices():
        source_type = source_type_for(name, content)
        if source_type is None:
            raise ValueError(f"Demo sample {name} is not an XML or PDF invoice")
        parsed = read_invoice_xml(invoice_xml(content, source_type))
        texts.extend(line.item_name for line in parsed.lines if line.item_name)
    return texts


def write_vectors(client: RecordingClient, path: Path) -> int:
    """The vectors of the booking history and the demo samples' lines, for the demo (ADR-020)."""
    texts = [line["text"] for invoice in history.packaged_history() for line in invoice["lines"]]
    unique = sorted(set(normalise(text) for text in [*texts, *_demo_texts()]))
    reply = client.embed(
        model=EMBEDDING_MODEL, texts=unique, dimensions=EMBEDDING_DIMENSIONS, task="similarity"
    )
    document = {
        "description": "Written by `invoiceguard-eval vectors` from recorded embeddings.",
        "model": EMBEDDING_MODEL,
        "dimensions": EMBEDDING_DIMENSIONS,
        "vectors": {
            text: embedding.encode_vector(vector)
            for text, vector in zip(unique, reply.vectors, strict=True)
        },
    }
    path.write_text(json.dumps(document, indent=1) + "\n", "utf-8", newline="\n")
    return len(unique)


def write_rulebook_vectors(client: RecordingClient, path: Path) -> int:
    """The vectors of the rulebook's sections (task `document`), keyed by the chunk's hash, so
    `make index` needs no key for them (R3-4b)."""
    chunks = rulebook_chunks.load(attack_eval.RULEBOOK_DIR)
    texts = [rulebook_chunks.embedding_text(c.title, c.heading, c.text) for c in chunks]
    reply = client.embed(
        model=EMBEDDING_MODEL, texts=texts, dimensions=EMBEDDING_DIMENSIONS, task="document"
    )
    document = {
        "description": "Written by `invoiceguard-eval vectors` from recorded embeddings.",
        "model": EMBEDDING_MODEL,
        "dimensions": EMBEDDING_DIMENSIONS,
        "vectors": {
            chunk.text_sha256: embedding.encode_vector(vector)
            for chunk, vector in zip(chunks, reply.vectors, strict=True)
        },
    }
    path.write_text(json.dumps(document, indent=1) + "\n", "utf-8", newline="\n")
    return len(chunks)


def run(args: argparse.Namespace) -> Path:
    client = RecordingClient(
        RECORDINGS_DIR,
        _live_client() if args.live else None,
        args.max_spend_usd,
        missing_as_failure=args.missing_as_failed,
    )
    manifest = load_manifest()
    result: dict[str, Any] = {
        "parser": evaluate.evaluate_parser(datasets.kosit_files(manifest, args.set))
        if "parser" in args.only
        else None,
        "extraction": _extraction(args, client) if "extraction" in args.only else None,
        "decisions": _decisions(args, client) if "decisions" in args.only else None,
        "attacks": _attacks(args, client) if "attacks" in args.only else None,
        "bookings": _bookings(client) if "bookings" in args.only else None,
        "rulebook": _rulebook(client) if "rulebook" in args.only else None,
    }
    created = datetime.now(UTC)
    result = {
        "meta": {
            "created_at": created.isoformat(timespec="seconds"),
            "git_commit": _git_commit(),
            "set": args.set,
            "model": args.model,
            "runs": args.runs,
            "efforts": args.efforts,
            "decision_effort": args.decision_effort,
            "threshold": str(THRESHOLD),
            "mode": "live" if args.live else "replay",
            "live_calls": client.live_calls,
            "replayed_calls": client.replayed,
            "live_spend_usd": str(client.spent_usd),
            "validator": bool(os.environ.get("INVOICEGUARD_EVAL_VALIDATOR_URL")),
            "embedding_model": EMBEDDING_MODEL,
        },
        **result,
    }
    out = args.out or REPORTS_DIR / f"latest-{args.set}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", "utf-8", newline="\n")
    return out


def run_gate(args: argparse.Namespace) -> None:
    current = gate.gate_metrics(json.loads(args.report.read_text("utf-8")), args.effort)
    baseline_path = args.baseline or BASELINES_DIR / f"{current['set']}.json"
    if args.write_baseline:
        gate.write_baseline(baseline_path, current)
        print(f"wrote {baseline_path}")
        return
    baseline = gate.read_baseline(baseline_path)
    for label, numbers in ((f"baseline {baseline_path}", baseline), ("report", current)):
        print(
            f"{label} (commit {numbers['git_commit']}): field accuracy "
            f"{numbers['field_accuracy']:.1%}, ${numbers['cost_usd_per_invoice']:.4f} per invoice, "
            f"{numbers['attacks_succeeded']} of {numbers['attack_cases']} attacks succeeded"
        )
    failures = gate.compare(baseline, current)
    if failures:
        sys.exit("Eval gate failed:\n" + "\n".join(f"- {failure}" for failure in failures))
    print("Eval gate passed.")


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    if args.command == "fetch":
        print(f"downloaded {fetch(load_manifest())} file(s); every cached file matches its pin")
    elif args.command == "generate":
        print(f"wrote {datasets.write_generated()} files to {datasets.GENERATED_DIR}")
        print(f"wrote {bookings.write_history()} booking lines to {bookings.HISTORY_PATH}")
    elif args.command == "vectors":
        client = RecordingClient(
            RECORDINGS_DIR, _live_client() if args.live else None, args.max_spend_usd
        )
        path = Path(str(history.VECTORS))
        print(f"wrote {write_vectors(client, path)} vectors to {path}")
        path = Path(str(rulebook_index.VECTORS))
        print(f"wrote {write_rulebook_vectors(client, path)} vectors to {path}; "
              f"${client.spent_usd} spent")  # fmt: skip
    elif args.command == "run":
        print(f"report: {run(args)}")
    elif args.command == "gate":
        run_gate(args)
    else:
        content = json.loads(args.report.read_text("utf-8"))
        path = args.report.resolve()
        repository = PACKAGE_DIR.parents[1]
        source = (
            path.relative_to(repository).as_posix()
            if path.is_relative_to(repository)
            else str(path)
        )
        notes = None if args.notes is None else args.notes.read_text("utf-8")
        markdown = report.render_results(content, args.effort, source, notes)
        args.out.write_text(markdown, "utf-8", newline="\n")
        print(f"wrote {args.out}")
