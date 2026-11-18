"""Run the parser and extraction evaluations and summarise them (ADR-019)."""

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from invoiceguard_api.checks import vat
from invoiceguard_api.checks.model import CheckContext, Validation
from invoiceguard_api.extraction import PdfExtractor
from invoiceguard_api.models import CheckStatus
from invoiceguard_api.parsing import ParsedInvoice, ParseError, read_invoice_xml
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS

from invoiceguard_evals.datasets import ExtractionCase
from invoiceguard_evals.metrics import (
    KEY_TERMS,
    FieldScore,
    LineScore,
    confidence_summary,
    normalise,
    percentile,
    ratio,
    score,
)
from invoiceguard_evals.recording import RecordingClient
from invoiceguard_evals.sources import SourceFile

# KoSIT file names: "01.01a-INVOICE_ubl" and "01.01a-INVOICE_uncefact" are one business case.
CASE_NAME = re.compile(r"^(?P<case>.+)-INVOICE_(?P<syntax>ubl|uncefact)$")
NOT_VALIDATED = Validation(outcome="not_applicable", reason="parser eval")


# --- Parser (KoSIT testsuite) -------------------------------------------------------------------


def _vat_ok(invoice: ParsedInvoice) -> bool:
    context = CheckContext(invoice, NOT_VALIDATED, None, None, ())
    return vat.check(context).status is CheckStatus.PASSED


def evaluate_parser(files: Sequence[tuple[SourceFile, bytes]]) -> dict[str, Any]:
    """Every file must parse with consistent amounts; the UBL and CII file of one business case
    must give the same terms (two readers, one truth)."""
    parsed: dict[str, ParsedInvoice] = {}
    failures = []
    for source, content in files:
        try:
            parsed[source.id] = read_invoice_xml(content)
        except ParseError as error:
            failures.append({"file": source.id, "error": str(error)})
    pairs: dict[str, dict[str, ParsedInvoice]] = defaultdict(dict)
    for file_id, invoice in parsed.items():
        if match := CASE_NAME.match(file_id):
            pairs[match["case"]][match["syntax"]] = invoice
    differences = []
    compared = 0
    for case, by_syntax in sorted(pairs.items()):
        if len(by_syntax) != 2:
            continue
        compared += 1
        fields, _ = score(by_syntax["ubl"], by_syntax["uncefact"])
        differences += [
            {"case": case, "term": f.term, "line": f.line_no, "ubl": f.expected, "cii": f.actual}
            for f in fields
            if not f.correct
        ]
    vat_failures = [file_id for file_id, invoice in parsed.items() if not _vat_ok(invoice)]
    return {
        "files": len(files),
        "parsed": len(parsed),
        "parse_failures": failures,
        "vat_math_failures": sorted(vat_failures),
        "pairs_compared": compared,
        "pairs_identical": compared - len({d["case"] for d in differences}),
        "pair_differences": differences,
    }


# --- Extraction ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionRun:
    case_id: str
    dataset: str
    run: int
    failure: str | None
    calls: int
    cost_usd: Decimal
    input_tokens: int
    output_tokens: int
    latency_ms: int
    fields: tuple[FieldScore, ...]
    lines: tuple[LineScore, ...]
    expected_lines: int
    actual_lines: int | None
    conflicts: tuple[dict[str, Any], ...]


def _typed(like: Any, text: str) -> Any:
    """The decoy as the same type as the true value, so it is normalised the same way."""
    if isinstance(like, date):
        return date.fromisoformat(text)
    return Decimal(text) if isinstance(like, Decimal) else text


def _conflicts(case: ExtractionCase, actual: ParsedInvoice | None, scores: list[FieldScore],
               threshold: Decimal) -> tuple[dict[str, Any], ...]:  # fmt: skip
    """For each conflict: did the model take the right value, the decoy, or something else,
    and did its confidence fall below the `low_confidence` threshold?"""
    by_term = {s.term: s for s in scores if s.line_no is None}
    outcomes = []
    for conflict in case.conflicts:
        field = by_term[conflict.term]
        got = None if actual is None else getattr(actual, conflict.term)
        decoy = _typed(getattr(case.truth, conflict.term), conflict.decoy)
        if field.correct:
            picked = "right"
        elif got is not None and normalise(conflict.term, got) == normalise(conflict.term, decoy):
            picked = "decoy"
        else:
            picked = "other"
        outcomes.append(
            {
                "kind": conflict.kind,
                "term": conflict.term,
                "picked": picked,
                "confidence": None if field.confidence is None else str(field.confidence),
                "flagged": field.confidence is not None and field.confidence < threshold,
            }
        )
    return tuple(outcomes)


def evaluate_extraction(
    cases: Sequence[ExtractionCase],
    extractor: PdfExtractor,
    client: RecordingClient,
    runs: int,
) -> list[ExtractionRun]:
    results = []
    for run in range(1, runs + 1):
        client.run = run
        for case in cases:
            result = extractor.extract(case.pdf)
            extraction = result.extraction
            actual = None if extraction is None else extraction.invoice
            fields, lines = score(
                case.truth, actual, () if extraction is None else extraction.confidences
            )
            calls = result.calls
            results.append(
                ExtractionRun(
                    case_id=case.case_id,
                    dataset=case.dataset,
                    run=run,
                    failure=result.failure,
                    calls=len(calls),
                    cost_usd=sum((c.cost_usd or Decimal(0) for c in calls), Decimal(0)),
                    input_tokens=sum(c.input_tokens or 0 for c in calls),
                    output_tokens=sum(c.output_tokens or 0 for c in calls),
                    latency_ms=sum(c.latency_ms for c in calls),
                    fields=tuple(fields),
                    lines=tuple(lines),
                    expected_lines=len(case.truth.lines),
                    actual_lines=None if actual is None else len(actual.lines),
                    conflicts=_conflicts(case, actual, fields, extractor.confidence_threshold),
                )
            )
    return results


def extraction_summary(runs: Sequence[ExtractionRun], threshold: Decimal) -> dict[str, Any]:
    """Accuracy, confidence, conflicts and cost over a list of runs (one per invoice and run)."""
    document = [f for r in runs for f in r.fields if f.line_no is None]
    line_terms = [f for r in runs for f in r.fields if f.line_no is not None]
    per_term = {
        term: ratio(
            sum(1 for f in document if f.term == term and f.correct),
            sum(1 for f in document if f.term == term),
        )
        for term in DOCUMENT_TERMS
    }
    key_ok = [
        all(f.correct for f in r.fields if f.line_no is None and f.term in KEY_TERMS) for r in runs
    ]
    pairs = [(f.confidence, f.correct) for f in document if f.confidence is not None]
    pairs += [(line.confidence, line.correct) for r in runs for line in r.lines
              if line.confidence is not None]  # fmt: skip
    conflicts = [c for r in runs for c in r.conflicts]
    latencies = [r.latency_ms / 1000 for r in runs if r.failure is None]
    succeeded = [r for r in runs if r.failure is None]
    return {
        "invoices": len(runs),
        "failed": len(runs) - len(succeeded),
        "field_accuracy": ratio(sum(f.correct for f in document), len(document)),
        "line_term_accuracy": ratio(sum(f.correct for f in line_terms), len(line_terms)),
        "document_accuracy": ratio(sum(key_ok), len(key_ok)),
        "line_count_match": ratio(
            sum(1 for r in runs if r.actual_lines == r.expected_lines), len(runs)
        ),
        "per_term": per_term,
        "confidence": confidence_summary(pairs, threshold),
        "conflicts": {
            "cases": len(conflicts),
            "right": sum(1 for c in conflicts if c["picked"] == "right"),
            "decoy": sum(1 for c in conflicts if c["picked"] == "decoy"),
            "other": sum(1 for c in conflicts if c["picked"] == "other"),
            "flagged": sum(1 for c in conflicts if c["flagged"]),
        },
        "cost_usd_mean": _mean([float(r.cost_usd) for r in succeeded]),
        "cost_usd_total": str(sum((r.cost_usd for r in runs), Decimal(0))),
        "input_tokens_mean": _mean([r.input_tokens for r in succeeded]),
        "output_tokens_mean": _mean([r.output_tokens for r in succeeded]),
        "latency_s_p50": percentile(latencies, 0.5),
        "latency_s_p95": percentile(latencies, 0.95),
        "retries": sum(r.calls - 1 for r in runs if r.calls > 1),
    }


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else sum(values) / len(values)


def run_details(runs: Sequence[ExtractionRun]) -> list[dict[str, Any]]:
    """Per invoice and run: the failure, the wrong fields and the conflicts, for the report."""
    return [
        {
            "case": r.case_id,
            "dataset": r.dataset,
            "run": r.run,
            "failure": r.failure,
            "cost_usd": str(r.cost_usd),
            "output_tokens": r.output_tokens,
            "latency_ms": r.latency_ms,
            "lines": [r.expected_lines, r.actual_lines],
            "wrong": [
                {k: v for k, v in asdict(f).items() if k != "correct"}
                | {"confidence": None if f.confidence is None else str(f.confidence)}
                for f in r.fields
                if not f.correct
            ],
            "conflicts": list(r.conflicts),
        }
        for r in runs
    ]
