"""Parser and extraction evaluation with fixed inputs and a fake model."""

from decimal import Decimal
from pathlib import Path
from typing import Any

from invoiceguard_api.extraction import PdfExtractor
from invoiceguard_api.llm import LLMError

from invoiceguard_evals.datasets import ExtractionCase
from invoiceguard_evals.evaluate import (
    evaluate_extraction,
    evaluate_parser,
    extraction_summary,
    run_details,
)
from invoiceguard_evals.recording import RecordingClient
from invoiceguard_evals.sources import SourceFile
from invoiceguard_evals.specs import ALL, truth
from invoiceguard_evals.ubl import to_ubl

from .fakes import ScriptedModel, reply_for

THRESHOLD = Decimal("0.8")
CONFLICT = next(spec for spec in ALL if spec.case_id == "c01_order_note")


def _run(
    tmp_path: Path, cases: list[ExtractionCase], replies: list[str | Exception], runs: int = 1
) -> list[Any]:
    client = RecordingClient(tmp_path, ScriptedModel(replies), Decimal(1))
    extractor = PdfExtractor(client, "gemini/test", THRESHOLD, "low")
    return evaluate_extraction(cases, extractor, client, runs)


def _case(spec_index: int = 0, pdf: bytes = b"%PDF-1") -> ExtractionCase:
    spec = ALL[spec_index]
    return ExtractionCase(spec.case_id, "generated", pdf, truth(spec), spec.conflicts)


def test_a_perfect_model_scores_everything_right(tmp_path: Path) -> None:
    runs = _run(tmp_path, [_case()], [reply_for(truth(ALL[0]))])

    summary = extraction_summary(runs, THRESHOLD)
    assert (summary["field_accuracy"], summary["line_term_accuracy"]) == (1.0, 1.0)
    assert (summary["document_accuracy"], summary["line_count_match"]) == (1.0, 1.0)
    assert summary["confidence"]["errors"] == 0
    assert summary["cost_usd_mean"] == 0.005
    assert summary["latency_s_p50"] == 9.0


def test_confident_errors_and_failures_are_counted(tmp_path: Path) -> None:
    cases = [_case(0), _case(1, b"%PDF-2")]
    replies: list[str | Exception] = [
        # Fictitious (demo bank code); not a secret.
        reply_for(truth(ALL[0]), payee_iban="DE89123456780000000099"),  # pragma: allowlist secret
        LLMError("quota", 10),
    ]

    runs = _run(tmp_path, cases, replies)
    summary = extraction_summary(runs, THRESHOLD)

    assert summary["failed"] == 1
    assert summary["document_accuracy"] == 0.0
    assert summary["confidence"]["confident_errors"] == 1
    assert summary["per_term"]["payee_iban"] == 0.0
    details = run_details(runs)
    assert details[0]["wrong"][0]["term"] == "payee_iban"
    assert "quota" in details[1]["failure"]


def test_a_conflict_records_the_decoy_and_the_confidence(tmp_path: Path) -> None:
    case = ExtractionCase(
        CONFLICT.case_id, "generated", b"%PDF-c", truth(CONFLICT), CONFLICT.conflicts
    )
    replies: list[str | Exception] = [
        reply_for(truth(CONFLICT), 0.9, order_reference="PO-2026-0030"),
        reply_for(truth(CONFLICT), 0.5),
        reply_for(truth(CONFLICT), 0.9, order_reference="PO-9999"),
    ]

    runs = _run(tmp_path, [case], replies, runs=3)

    picked = [(r.conflicts[0]["picked"], r.conflicts[0]["flagged"]) for r in runs]
    assert picked == [("decoy", False), ("right", True), ("other", False)]
    summary = extraction_summary(runs, THRESHOLD)["conflicts"]
    assert summary == {"cases": 3, "right": 1, "decoy": 1, "other": 1, "flagged": 1}


def _kosit(file_id: str, content: bytes) -> tuple[SourceFile, bytes]:
    return SourceFile(
        id=file_id, set="kosit", repository="r", path=f"{file_id}.xml", sha256="0" * 64
    ), content


def test_parser_eval_compares_the_ubl_and_cii_file_of_a_case() -> None:
    same = to_ubl(ALL[0])
    other = to_ubl(ALL[3])
    files = [
        _kosit("01.01a-INVOICE_ubl", same),
        _kosit("01.01a-INVOICE_uncefact", same),
        _kosit("01.02a-INVOICE_ubl", same),
        _kosit("01.02a-INVOICE_uncefact", other),
        _kosit("01.03a-INVOICE_ubl", same),
        _kosit("broken", b"<Invoice"),
        _kosit("changed_totals", to_ubl(ALL[-3])),
    ]

    result = evaluate_parser(files)

    assert (result["files"], result["parsed"]) == (7, 6)
    assert result["parse_failures"][0]["file"] == "broken"
    assert (result["pairs_compared"], result["pairs_identical"]) == (2, 1)
    assert {d["case"] for d in result["pair_differences"]} == {"01.02a"}
    assert result["vat_math_failures"] == ["changed_totals"]
