"""Model comparison (R4-6, ADR-026): the app's PDF extraction with each model on one small set,
the 6 demo samples as PDFs plus the `small` set's corpus and generated PDFs.

Each model gets the same `PdfExtractor` (prompt, schema, retries, cost per call) the app uses, at
the app's reasoning effort, one run per invoice. Models run in the given order on one recording
client, so one spend cap covers them all: when it is reached, the model in progress and every
model after it are reported as incomplete. The Markdown is built from the replies alone, so a
replay reproduces it byte for byte (`--check` in CI).
"""

import importlib.metadata
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from invoiceguard_api.extraction import PdfExtractor
from invoiceguard_api.llm import ReasoningEffort
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS

from invoiceguard_evals.datasets import ExtractionCase
from invoiceguard_evals.evaluate import ExtractionRun, evaluate_extraction, extraction_summary
from invoiceguard_evals.recording import RecordingClient, SpendCapReached
from invoiceguard_evals.report import num, pct, usd

# Cheapest first: if the cap stops a run, the dearest model is the one cut short.
MODELS = (
    "gemini/gemini-3.5-flash-lite",
    "gemini/gemini-3.8-flash",
    "gemini/gemini-3.1-pro-preview",
)
# A live comparison keeps at least this much free before each call (`RecordingClient`).
MIN_RESERVE_USD = Decimal("0.02")
DATASETS = ("demo", "corpus", "generated")
PER_MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelResult:
    model: str
    planned: int
    runs: tuple[ExtractionRun, ...]
    # Why the run stopped before every invoice was done; None when it is complete.
    stopped: str | None


def compare(
    cases: Sequence[ExtractionCase],
    client: RecordingClient,
    models: Sequence[str],
    effort: ReasoningEffort,
    threshold: Decimal,
) -> list[ModelResult]:
    results = []
    stopped: str | None = None
    for model in models:
        extractor = PdfExtractor(client, model, threshold, effort)
        runs: list[ExtractionRun] = []
        for case in cases if stopped is None else ():
            try:
                runs += evaluate_extraction([case], extractor, client, 1)
            except SpendCapReached as error:
                stopped = str(error)
                break
        complete = len(runs) == len(cases)
        results.append(ModelResult(model, len(cases), tuple(runs), None if complete else stopped))
    return results


def prices(model: str) -> tuple[Decimal, Decimal] | None:
    """USD per million input and output tokens in LiteLLM's pinned price table (ADR-004)."""
    # Imported here: LiteLLM takes seconds to import. The client module goes first: it pins
    # LiteLLM to its bundled price table.
    import invoiceguard_api.llm.litellm_client  # noqa: F401
    import litellm

    entry = litellm.model_cost.get(model)
    if entry is None:
        return None
    return (
        Decimal(str(entry["input_cost_per_token"])) * PER_MILLION,
        Decimal(str(entry["output_cost_per_token"])) * PER_MILLION,
    )


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    return lines + ["| " + " | ".join(row) + " |" for row in rows]


def _price(model: str) -> str:
    price = prices(model)
    if price is None:
        return "unknown"
    return f"${price[0].normalize():f} / ${price[1].normalize():f}"


def _days(days: set[str]) -> str:
    if not days:
        return "-"
    first, last = min(days), max(days)
    return first if first == last else f"{first} to {last}"


def _summary_row(result: ModelResult, s: dict[str, Any], days: set[str]) -> list[str]:
    done = f"{s['invoices']} of {result.planned}"
    c = s["confidence"]
    return [
        f"`{result.model}`",
        _price(result.model),
        _days(days),
        done,
        str(s["failed"]),
        pct(s["field_accuracy"]),
        pct(s["document_accuracy"]),
        pct(s["line_term_accuracy"]),
        f"{c['confident_errors']} of {c['errors']}",
        num(s["latency_s_p50"], 1),
        num(s["latency_s_p95"], 1),
        usd(s["cost_usd_mean"]),
        usd(float(s["cost_usd_total"])),
    ]


def _wrong(result: ModelResult) -> list[list[str]]:
    rows = []
    for run in result.runs:
        if run.failure is not None:
            rows.append([run.case_id, "(failed)", "-", run.failure])
            continue
        for field in run.fields:
            if field.correct:
                continue
            term = field.term if field.line_no is None else f"line {field.line_no}: {field.term}"
            rows.append([run.case_id, term, f"`{field.expected}`", f"`{field.actual}`"])
    return rows


def render(
    results: Sequence[ModelResult],
    recorded_on: dict[str, set[str]],
    effort: ReasoningEffort,
    threshold: Decimal,
) -> str:
    summaries = {r.model: extraction_summary(r.runs, threshold) for r in results}
    invoices = results[0].planned if results else 0
    lines = [
        "# Model comparison",
        "",
        "Generated by `invoiceguard-eval models` (`make eval-models`) from the recorded replies in "
        "`packages/evals/recordings`; CI replays them and fails when this file differs. Which "
        "model stays the default, and why: "
        "[ADR-026](../decisions/ADR-026-default-extraction-model.md).",
        "",
        f"- **Invoices:** {invoices} PDFs, one run each: the 6 demo samples drawn as PDFs "
        "(`packages/evals/datasets/demo`, the truth is the demo XML), and the `small` set's 2 "
        "corpus PDFs (truth: their embedded XML) and 4 generated PDFs (truth: the spec).",
        f"- **Setup:** the app's `PdfExtractor` (prompt, schema, up to 3 attempts), reasoning "
        f"effort `{effort}`, `low_confidence` threshold {threshold}.",
        "- **Models:** the Gemini API model IDs below; prices are USD per million input / output "
        f"tokens from the price table of LiteLLM {importlib.metadata.version('litellm')} "
        "(ADR-004), and the cost of each call is computed from it.",
        "- **Recorded:** the day(s) the replies were recorded, per model.",
        "",
        "## Summary",
        "",
        "Fields: document terms right, a failed extraction counting as all wrong. Documents: all "
        "key terms right (invoice number, dates, seller, VAT ID, IBAN, totals). Confident errors: "
        "wrong fields with a confidence at or above the threshold, of all wrong fields. Latency "
        "per invoice, retries included.",
        "",
        *_table(
            [
                "Model",
                "Price in / out",
                "Recorded",
                "Invoices",
                "Failed",
                "Fields",
                "Documents",
                "Line terms",
                "Confident errors",
                "p50 s",
                "p95 s",
                "Cost / invoice",
                "Total",
            ],
            [_summary_row(r, summaries[r.model], recorded_on.get(r.model, set())) for r in results],
        ),
    ]
    stopped = [r for r in results if r.stopped is not None]
    if stopped:
        lines += ["", "**Incomplete:** " + "; ".join(
            f"`{r.model}` stopped after {len(r.runs)} of {r.planned} invoices" for r in stopped
        ) + f". Reason: {stopped[0].stopped}"]  # fmt: skip
    lines += [
        "",
        "## Accuracy per field",
        "",
        *_table(
            ["Term", "BT", *(f"`{r.model}`" for r in results)],
            [
                [term, code, *(pct(summaries[r.model]["per_term"][term]) for r in results)]
                for term, code in DOCUMENT_TERMS.items()
            ],
        ),
        "",
        "## Field accuracy per dataset",
        "",
        *_table(
            ["Dataset", *(f"`{r.model}`" for r in results)],
            [
                [
                    name,
                    *(
                        pct(
                            extraction_summary(
                                [run for run in r.runs if run.dataset == name], threshold
                            )["field_accuracy"]
                        )
                        for r in results
                    ),
                ]
                for name in DATASETS
            ],
        ),
        "",
        "## Wrong fields",
        "",
    ]
    for result in results:
        wrong = _wrong(result)
        lines += [f"### `{result.model}`", ""]
        lines += (
            [*_table(["Invoice", "Term", "Expected", "Extracted"], wrong), ""]
            if wrong
            else ["None.", ""]
        )
    return "\n".join(lines)
