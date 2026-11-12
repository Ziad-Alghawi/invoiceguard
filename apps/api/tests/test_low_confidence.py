"""The low_confidence check (ADR-010): a pure function of the context, as the other checks."""

from decimal import Decimal

import pytest

from invoiceguard_api.checks import low_confidence, run_checks
from invoiceguard_api.checks.model import CheckContext, Validation
from invoiceguard_api.extraction import FieldConfidence
from invoiceguard_api.models import CheckStatus, SourceType
from invoiceguard_api.parsing import parse_invoice

THRESHOLD = Decimal("0.8")
SURE = Decimal("0.95")
UNSURE = Decimal("0.6")


def confidences(**low: Decimal) -> tuple[FieldConfidence, ...]:
    terms = {"buyer_name": "BT-44", "payee_iban": "BT-84", "gross_total": "BT-112"}
    fields = [
        FieldConfidence(name, code, None, low.get(name, SURE), {"page": 1, "snippet": name})
        for name, code in terms.items()
    ]
    fields.append(FieldConfidence("line 1", None, 1, low.get("line_1", SURE), None))
    return tuple(fields)


def context(samples: dict[str, bytes], fields: tuple[FieldConfidence, ...]) -> CheckContext:
    return CheckContext(
        invoice=parse_invoice(samples["ubl_xrechnung"], SourceType.XML),
        validation=Validation(outcome="not_applicable", reason="extracted from a PDF"),
        supplier=None,
        order=None,
        other_invoices=(),
        confidences=fields,
        confidence_threshold=THRESHOLD,
    )


def test_xml_invoices_get_no_result(samples: dict[str, bytes]) -> None:
    assert low_confidence.check(context(samples, ())) == []
    assert "low_confidence" not in {r.type for r in run_checks(context(samples, ()))}


def test_all_fields_sure_passes(samples: dict[str, bytes]) -> None:
    [result] = low_confidence.check(context(samples, confidences()))

    assert result.status is CheckStatus.PASSED
    assert result.evidence == {"threshold": "0.8", "fields": []}


@pytest.mark.parametrize("name", ["buyer_name", "line_1"])
def test_low_confidence_on_other_fields_warns(samples: dict[str, bytes], name: str) -> None:
    [result] = low_confidence.check(context(samples, confidences(**{name: UNSURE})))

    assert result.status is CheckStatus.WARNING
    shown = name.replace("_", " ") if name == "line_1" else name
    assert result.message == f"Low confidence below 0.8; check against the PDF: {shown}."
    assert [field["name"] for field in result.evidence["fields"]] == [shown]
    assert result.evidence["fields"][0]["confidence"] == "0.6"


@pytest.mark.parametrize("name", ["payee_iban", "gross_total"])
def test_low_confidence_on_iban_or_total_fails(samples: dict[str, bytes], name: str) -> None:
    fields = confidences(**{name: UNSURE, "buyer_name": UNSURE})
    [result] = low_confidence.check(context(samples, fields))

    assert result.status is CheckStatus.FAILED
    assert f"payee IBAN or a total ({name})" in result.message
    assert {field["name"] for field in result.evidence["fields"]} == {name, "buyer_name"}


def test_exactly_the_threshold_is_enough(samples: dict[str, bytes]) -> None:
    [result] = low_confidence.check(context(samples, confidences(payee_iban=THRESHOLD)))

    assert result.status is CheckStatus.PASSED


def test_kosit_is_skipped_for_extracted_invoices(samples: dict[str, bytes]) -> None:
    results = {r.type: r for r in run_checks(context(samples, confidences()))}

    assert results["kosit"].status is CheckStatus.SKIPPED
    assert results["kosit"].message == "extracted from a PDF"
