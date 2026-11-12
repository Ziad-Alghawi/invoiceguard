"""Differential test (ADR-005): our parser and factur-x's own parser must agree on every sample.

factur-x's parser is used here only, never in production code.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from facturx import parse_ubl_cii_xml

from invoiceguard_api.models import SourceType
from invoiceguard_api.parsing import parse_invoice
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS, LINE_TERMS

# factur-x nests the party terms in their business groups (BG-4 seller, BG-7 buyer).
PARTY_TERMS = {
    "BT-27": ("BG-4", "name"),
    "BT-31": ("BG-4", "vat_identifier"),
    "BT-44": ("BG-7", "name"),
    "BT-48": ("BG-7", "vat_identifier"),
}
AMOUNT_TERMS = {"BT-109", "BT-110", "BT-112", "BT-115", "BT-129", "BT-131", "BT-146", "BT-152"}


def _normalise(code: str, value: Any) -> Any:
    if value is None:
        return None
    if code in AMOUNT_TERMS:
        return Decimal(str(value))
    return value


def _reference_value(data: dict[str, Any], code: str) -> Any:
    if code in PARTY_TERMS:
        group, key = PARTY_TERMS[code]
        return data.get(group, {}).get(key)
    return data.get(code)


@pytest.mark.parametrize("sample", ["cii_xrechnung", "ubl_xrechnung", "zugferd2_basic"])
def test_agrees_with_facturx_parser(samples: dict[str, bytes], sample: str) -> None:
    ours = parse_invoice(samples[sample], SourceType.XML)
    reference = parse_ubl_cii_xml(samples[sample], check_xsd=False)

    for name, code in DOCUMENT_TERMS.items():
        expected = _reference_value(reference, code)
        actual = getattr(ours, name)
        assert _normalise(code, actual) == _normalise(code, expected), code
        if isinstance(actual, date):
            assert isinstance(expected, date), code

    reference_lines = reference.get("BG-25", [])
    assert len(ours.lines) == len(reference_lines)
    for line, reference_line in zip(ours.lines, reference_lines, strict=True):
        for name, code in LINE_TERMS.items():
            expected = reference_line.get(code)
            assert _normalise(code, getattr(line, name)) == _normalise(code, expected), code
