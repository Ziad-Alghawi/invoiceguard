"""Field locations (P1): the share of stored values found in the PDFs' text layer, by code."""

from dataclasses import replace

from invoiceguard_evals import datasets
from invoiceguard_evals.location_eval import evaluate_locations, render_locations


def test_every_field_of_the_demo_pdfs_is_located() -> None:
    result = evaluate_locations(datasets.demo_cases())
    demo = result["datasets"]["demo"]
    assert demo["invoices"] == 6
    assert demo["located"] == demo["fields"] > 100
    assert result["missed"] == []


def test_a_value_the_pdf_does_not_print_is_missed_and_reported() -> None:
    case = datasets.demo_cases()[0]
    changed = replace(case, truth=case.truth.model_copy(update={"invoice_number": "NOT-PRINTED"}))
    result = evaluate_locations([changed])
    assert result["missed"] == [{"case": case.case_id, "code": "BT-1", "line": None}]
    markdown = "\n".join(render_locations(result))
    assert "| BT-1 | invoice_number | 0 of 1 |" in markdown
    assert "Fields located: **" in markdown
