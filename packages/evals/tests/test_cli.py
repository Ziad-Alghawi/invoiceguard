"""The CLI end to end with a fake model: a live run records, a replay run reproduces it for free,
and the report becomes Markdown."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from invoiceguard_api.booking import history

from invoiceguard_evals import cli
from invoiceguard_evals.attacks import ATTACKS
from invoiceguard_evals.datasets import GENERATED_DIR, generated_cases
from invoiceguard_evals.sources import Manifest
from invoiceguard_evals.specs import ALL, InvoiceSpec, truth

from .fakes import RoutingModel, ScriptedModel, reply_for

EMPTY = Manifest(repositories={}, files=())
SMALL = [spec for spec in ALL if "small" in spec.tags]


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Recordings in a temporary folder and no corpus files, so the run uses only what the test
    provides."""
    monkeypatch.setattr(cli, "RECORDINGS_DIR", tmp_path / "recordings")
    monkeypatch.setattr(cli, "load_manifest", lambda: EMPTY)
    return tmp_path


def _model(monkeypatch: pytest.MonkeyPatch, replies: list[str | Exception]) -> ScriptedModel:
    model = ScriptedModel(replies)
    monkeypatch.setattr(cli, "_live_client", lambda: model)
    return model


def _run(*args: str) -> dict[str, Any]:
    out = Path(args[args.index("--out") + 1])
    cli.main(["run", *args])
    report: dict[str, Any] = json.loads(out.read_text("utf-8"))
    return report


def test_live_records_and_replay_reproduces(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = generated_cases("small")
    _model(monkeypatch, [reply_for(case.truth) for case in cases])
    common = ["--only", "parser,extraction", "--set", "small"]

    live = _run(*common, "--live", "--max-spend-usd", "1", "--out", str(isolated / "live.json"))
    replay = _run(*common, "--out", str(isolated / "replay.json"))

    assert live["meta"]["live_calls"] == len(cases)
    assert (replay["meta"]["live_calls"], replay["meta"]["replayed_calls"]) == (0, len(cases))
    assert replay["extraction"]["low"]["summary"]["field_accuracy"] == 1.0
    assert replay["extraction"] == live["extraction"]


def test_decisions_and_the_markdown_report(
    isolated: Path, monkeypatch: pytest.MonkeyPatch, eval_database_url: str
) -> None:
    monkeypatch.setenv("INVOICEGUARD_EVAL_DATABASE_URL", eval_database_url)
    monkeypatch.delenv("INVOICEGUARD_EVAL_VALIDATOR_URL", raising=False)
    with_decisions = [s for s in SMALL if s.expected is not None]
    _model(monkeypatch, [reply_for(truth(spec)) for spec in with_decisions])
    out = isolated / "decisions.json"

    report = _run("--only", "decisions", "--live", "--max-spend-usd", "1", "--out", str(out))

    assert report["decisions"]["xml"]["summary"]["as_expected"] == len(with_decisions)
    assert report["decisions"]["pdf"]["summary"]["as_expected"] == len(with_decisions)
    results = isolated / "results.md"
    cli.main(["report", str(out), "--out", str(results)])
    markdown = results.read_text("utf-8")
    assert markdown.startswith("# Results")
    assert "## Decisions: fraud set through the app" in markdown


def test_decisions_need_an_eval_database(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INVOICEGUARD_EVAL_DATABASE_URL", raising=False)

    with pytest.raises(SystemExit, match="INVOICEGUARD_EVAL_DATABASE_URL"):
        cli.main(["run", "--only", "decisions", "--out", str(isolated / "x.json")])


def test_live_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INVOICEGUARD_LLM_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="INVOICEGUARD_LLM_API_KEY"):
        cli._live_client()


@pytest.mark.parametrize("args", [["run", "--efforts", "turbo"], ["run", "--only", "everything"]])
def test_bad_arguments_are_refused(args: list[str]) -> None:
    with pytest.raises(SystemExit):
        cli.main(args)


def test_the_attack_set_records_replays_and_reports(
    isolated: Path, monkeypatch: pytest.MonkeyPatch, eval_database_url: str
) -> None:
    monkeypatch.setenv("INVOICEGUARD_EVAL_DATABASE_URL", eval_database_url)
    monkeypatch.delenv("INVOICEGUARD_EVAL_VALIDATOR_URL", raising=False)
    small = [spec for spec in ATTACKS if "small" in spec.tags]

    def digest(spec: InvoiceSpec) -> str:
        return hashlib.sha256((GENERATED_DIR / f"{spec.case_id}.pdf").read_bytes()).hexdigest()

    truths = {
        digest(spec): truth(spec)
        for spec in small
        if spec.attack is not None and spec.attack.variant == "pdf"
    }
    finish = json.dumps(
        {
            "action": "finish",
            "tool_calls": [],
            "finding": "Changed IBAN.",
            "email_subject": "Rückfrage",
            "email_body": "Bitte bestätigen.",
        }
    )
    model = RoutingModel(truths, finish)
    monkeypatch.setattr(cli, "_live_client", lambda: model)
    common = ["--only", "attacks", "--set", "small"]

    live = _run(*common, "--live", "--max-spend-usd", "1", "--out", str(isolated / "a.json"))
    replay = _run(*common, "--out", str(isolated / "b.json"))

    attacks = live["attacks"]
    assert (attacks["cases"], attacks["succeeded"], attacks["succeeded_model_only"]) == (
        len(small), 0, 0
    )  # fmt: skip
    assert attacks["agent_runs"] > 0
    assert replay["meta"]["live_calls"] == 0
    assert replay["meta"]["replayed_calls"] == model.calls
    assert replay["attacks"]["details"] == attacks["details"]
    results = isolated / "results.md"
    cli.main(["report", str(isolated / "b.json"), "--out", str(results)])
    assert "## Attacks: prompt injection through the app and the agent" in results.read_text(
        "utf-8"
    )


def test_the_booking_eval_records_replays_and_reports(
    isolated: Path, monkeypatch: pytest.MonkeyPatch, eval_database_url: str
) -> None:
    monkeypatch.setenv("INVOICEGUARD_EVAL_DATABASE_URL", eval_database_url)
    _model(monkeypatch, [])
    common = ["--only", "bookings", "--set", "small"]

    live = _run(*common, "--live", "--max-spend-usd", "1", "--out", str(isolated / "a.json"))
    replay = _run(*common, "--out", str(isolated / "b.json"))

    bookings = live["bookings"]
    assert bookings["history_bookings"] == 159
    assert bookings["summary"]["lines"] == 62
    # Fake vectors carry no meaning, but a booked wording finds itself.
    assert bookings["by_kind"]["seen"]["vector"]["top1"] == 1.0
    assert replay["meta"]["live_calls"] == 0
    assert replay["bookings"]["cases"] == bookings["cases"]
    results = isolated / "results.md"
    cli.main(["report", str(isolated / "b.json"), "--out", str(results)])
    assert "## Booking suggestions and retrieval" in results.read_text("utf-8")


def test_the_vectors_command_writes_the_packaged_vectors(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _model(monkeypatch, [])
    path = isolated / "vectors.json"
    monkeypatch.setattr(history, "VECTORS", path)

    cli.main(["vectors", "--live", "--max-spend-usd", "1"])
    written = json.loads(path.read_text("utf-8"))
    cli.main(["vectors"])

    assert json.loads(path.read_text("utf-8")) == written
    assert written["dimensions"] == 768
    assert "Notebook 14 Zoll, 32 GB RAM" in written["vectors"]
    assert len(written["vectors"]) == 59
