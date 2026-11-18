"""docs/results.md from a report: every section, built from real evaluation output."""

import hashlib
from decimal import Decimal
from pathlib import Path
from typing import Any

from facturx import generate_from_binary
from invoiceguard_api.extraction import PdfExtractor
from invoiceguard_api.llm import LLMError

from invoiceguard_evals.datasets import GENERATED_DIR, ExtractionCase, corpus_cases
from invoiceguard_evals.evaluate import (
    evaluate_extraction,
    evaluate_parser,
    extraction_summary,
    run_details,
)
from invoiceguard_evals.metrics import Decision, decision_summary
from invoiceguard_evals.recording import RecordingClient
from invoiceguard_evals.report import num, pct, render_results, usd
from invoiceguard_evals.sources import Manifest, Repository, SourceFile, cache_path
from invoiceguard_evals.specs import ALL, truth
from invoiceguard_evals.ubl import to_ubl

from .fakes import ScriptedModel, reply_for
from .test_sources import API_FIXTURES

THRESHOLD = Decimal("0.8")
CONFLICT = next(spec for spec in ALL if spec.case_id == "c01_order_note")


def _report(tmp_path: Path) -> dict[str, Any]:
    cases = [
        ExtractionCase(
            CONFLICT.case_id, "generated", b"%PDF-c", truth(CONFLICT), CONFLICT.conflicts
        ),
        ExtractionCase(ALL[0].case_id, "corpus", b"%PDF-0", truth(ALL[0])),
    ]
    model = ScriptedModel(
        [reply_for(truth(CONFLICT), 0.9, order_reference="PO-2026-0030"), LLMError("quota", 5)]
    )
    client = RecordingClient(tmp_path, model, Decimal(1))
    runs = evaluate_extraction(cases, PdfExtractor(client, "m", THRESHOLD, "low"), client, 1)
    parser_file = SourceFile(
        id="01.01a-INVOICE_ubl", set="kosit", repository="r", path="x", sha256="0" * 64
    )
    decisions = [
        Decision(
            "f01",
            "xml",
            "ready",
            frozenset(),
            "blocked",
            frozenset({"iban"}),
            "changed_iban",
            "iban",
        )
    ]
    return {
        "meta": {
            "created_at": "2026-11-18T12:00:00+00:00",
            "git_commit": "abc1234",
            "set": "small",
            "model": "m",
            "runs": 1,
            "threshold": "0.8",
            "live_spend_usd": "0.01",
        },
        "parser": evaluate_parser([(parser_file, to_ubl(ALL[0])), (parser_file, b"<x")]),
        "extraction": {
            "low": {
                "summary": extraction_summary(runs, THRESHOLD),
                "by_dataset": {"generated": extraction_summary(runs[:1], THRESHOLD)},
                "details": run_details(runs),
            }
        },
        "decisions": {
            "xml": {
                "summary": decision_summary(decisions),
                "cases": [
                    {
                        "case": "f01",
                        "status": "ready",
                        "flags": [],
                        "expected_status": "blocked",
                        "expected_flags": ["iban"],
                        "as_expected": False,
                    }
                ],
            }
        },
    }


def test_every_section_is_rendered(tmp_path: Path) -> None:
    markdown = render_results(_report(tmp_path), "low", "packages/evals/reports/x.json")

    for heading in (
        "# Results",
        "## Parser: KoSIT testsuite (no model)",
        "## Extraction by thinking level",
        "## Extraction at `low`",
        "## Decisions: fraud set through the app",
    ):
        assert heading in markdown
    assert "(failed: 01.01a-INVOICE_ubl)" in markdown
    assert "| c01_order_note | 1 | order_note | order_reference | decoy | 0.900 |" in markdown
    assert "quota" in markdown
    assert "- f01: ready with flags none (expected blocked with iban)" in markdown


def test_the_chosen_level_needs_to_be_in_the_report(tmp_path: Path) -> None:
    markdown = render_results(_report(tmp_path), "high", "x.json")

    assert "## Extraction by thinking level" in markdown
    assert "## Extraction at" not in markdown


def test_formats() -> None:
    assert (pct(None), pct(0.98765)) == ("-", "98.8 %")
    assert (num(None), num(1.234, 1)) == ("-", "1.2")
    assert (usd(None), usd(0.00567)) == ("-", "$0.0057")


def test_corpus_cases_take_the_truth_from_the_xml_with_overrides(tmp_path: Path) -> None:
    pdf = (GENERATED_DIR / "g01_buerobedarf_classic.pdf").read_bytes()
    zugferd = bytes(
        generate_from_binary(
            pdf, (API_FIXTURES / "zugferd2_basic.xml").read_bytes(), check_xsd=False
        )
    )
    source = SourceFile(
        id="zf",
        set="corpus",
        repository="r",
        path="zf.pdf",
        sha256=hashlib.sha256(zugferd).hexdigest(),
        truth_overrides={"due_date": "2030-01-31"},
        note="printed",
    )
    manifest = Manifest(
        repositories={"r": Repository(home="h", raw_url="https://x", commit="c", licence="l")},
        files=(source,),
    )
    path = cache_path(source, tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(zugferd)

    (case,) = corpus_cases(manifest, "full", tmp_path)

    assert case.truth.due_date is not None and case.truth.due_date.isoformat() == "2030-01-31"
    assert case.pdf != zugferd
    assert corpus_cases(manifest, "small", tmp_path) == []
