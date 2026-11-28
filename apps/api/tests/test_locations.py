"""Click-to-highlight (P1, ADR-029): field values found by code in a PDF's text layer."""

import uuid
from typing import Any

import pytest
from facturx import generate_from_binary
from fastapi.testclient import TestClient

from conftest import INVOICE_TEXT, poll_until_done, text_pdf
from invoiceguard_api.locations import (
    FieldToLocate,
    UnreadablePdf,
    locate_fields,
    read_text_layer,
)
from invoiceguard_api.locations.matching import value_pattern

# Fictitious (fake bank code), as in the fixtures; not a secret.
IBAN = "DE60123456780000000003"  # pragma: allowlist secret
# A thousands separator some programs print.
NBSP = chr(0xA0)


def _printed(code: str, value: str, text: str) -> str | None:
    pattern = value_pattern(code, value)
    assert pattern is not None
    found = pattern.search(text)
    return found.group(0) if found else None


@pytest.mark.parametrize(
    ("value", "text", "printed"),
    [
        ("1234.50", "Gesamt 1.234,50 EUR", "1.234,50"),
        ("1234.50", "Total 1,234.50 EUR", "1,234.50"),
        ("1234.50", "Summe 1234,50 €", "1234,50"),
        ("1234.50", "Summe 1 234,50 €", "1 234,50"),
        ("1234.50", f"Summe 1{NBSP}234,50 €", f"1{NBSP}234,50"),
        ("9.9000", "Preis 9,9000 €", "9,9000"),
        ("9.9000", "Preis 9,90 €", "9,90"),
        ("-0.23", "Abschläge -0,23", "-0,23"),
        ("-0.23", "Abschläge 0,23", "0,23"),
    ],
)
def test_amounts_in_german_and_english_formats(value: str, text: str, printed: str) -> None:
    assert _printed("BT-112", value, text) == printed


@pytest.mark.parametrize(
    "text",
    [
        "Betrag 11.234,50",  # inside a longer number
        "Betrag 1.234,501",  # another number with more decimals
        "Betrag 1.234,05",
        "Betrag 234,50",
    ],
)
def test_an_amount_is_not_found_inside_another_number(text: str) -> None:
    assert _printed("BT-112", "1234.50", text) is None


@pytest.mark.parametrize(
    ("text", "printed"),
    [
        ("Rechnungsdatum: 05.11.2026", "05.11.2026"),
        ("Datum 5.11.26", "5.11.26"),
        ("Date 2026-11-05", "2026-11-05"),
        ("Date 05/11/2026", "05/11/2026"),
        ("Date 11/05/2026", "11/05/2026"),
        ("am 5. November 2026", "5. November 2026"),
        ("Datum 05. Nov. 2026", "05. Nov. 2026"),
        ("Date November 5, 2026", "November 5, 2026"),
        ("Date 5 Nov 2026", "5 Nov 2026"),
    ],
)
def test_dates_in_german_and_english_formats(text: str, printed: str) -> None:
    assert _printed("BT-2", "2026-11-05", text) == printed


def test_a_date_is_not_found_in_another_date() -> None:
    assert _printed("BT-2", "2026-11-05", "Leistung 15.11.2026, Zahlung 05.11.2027") is None


@pytest.mark.parametrize(
    "text",
    [
        f"IBAN {IBAN}",
        "IBAN DE60 1234 5678 0000 0000 03",
        "iban: de60 1234 5678 0000 0000 03",
    ],
)
def test_an_iban_with_or_without_spaces(text: str) -> None:
    assert _printed("BT-84", IBAN, text) is not None


def test_an_iban_is_not_found_in_a_longer_one() -> None:
    assert _printed("BT-84", IBAN, "IBAN DE60 1234 5678 0000 0000 031") is None


def test_names_across_a_line_break_and_codes_as_words() -> None:
    assert _printed("BT-27", "Demo IT-Service GmbH", "Demo IT-Service\nGmbH") is not None
    assert _printed("BT-3", "380", "RECHNUNG Nr. 1") == "RECHNUNG"
    assert _printed("BT-130", "HUR", "6 Std 95,00") == "Std"
    assert _printed("BT-5", "EUR", "Betrag in €") == "€"
    assert _printed("BT-129", "3.000", "Menge 3 Stk") == "3"


def _locate(fields: list[FieldToLocate], lines: list[str]) -> dict[tuple[str, int | None], Any]:
    pages = read_text_layer(text_pdf(lines))
    return {(loc.code, loc.line_no): loc for loc in locate_fields(fields, pages)}


def test_values_found_in_a_real_text_layer_with_boxes_on_the_page() -> None:
    located = _locate(
        [
            FieldToLocate("BT-84", None, IBAN),
            FieldToLocate("BT-112", None, "5137.23"),
            FieldToLocate("BT-9", None, "2026-11-19"),
            FieldToLocate("BT-1", None, "NOT-PRINTED-1"),
        ],
        INVOICE_TEXT,
    )
    iban = located[("BT-84", None)]
    assert iban.located and iban.method == "text"
    (box,) = iban.boxes
    assert box.page == 1
    # The last printed line of the page, in the left half, in fractions of the page.
    assert 0 < box.x0 < box.x1 < 1 and 0 < box.y0 < box.y1 < 0.3
    assert located[("BT-112", None)].located
    assert located[("BT-9", None)].located
    missing = located[("BT-1", None)]
    assert not missing.located and missing.method is None and missing.boxes == ()


def test_line_terms_are_found_on_their_own_row() -> None:
    located = _locate(
        [
            FieldToLocate("BT-129", 1, "3"),
            FieldToLocate("BT-153", 1, "Notebook 14 Zoll, 32 GB RAM"),
            FieldToLocate("BT-129", 2, "6"),
            FieldToLocate("BT-153", 2, "Einrichtung und Inbetriebnahme"),
        ],
        INVOICE_TEXT,
    )
    rows = {line: located[("BT-153", line)].boxes[0] for line in (1, 2)}
    for line in (1, 2):
        quantity = located[("BT-129", line)].boxes[0]
        assert quantity.y0 < rows[line].y1 and rows[line].y0 < quantity.y1
        assert quantity.x0 > rows[line].x1


def test_llm_fields_use_their_evidence_page_and_text() -> None:
    located = _locate(
        [
            FieldToLocate(
                "BT-84", None, IBAN, {"page": 1, "snippet": "auf IBAN DE60 1234 5678 0000 0000 03"}
            ),
            # The printed text is not on the page and the value is not either.
            FieldToLocate("BT-13", None, "PO-9999", {"page": 1, "snippet": "Bestellung PO-9999"}),
            # A page the PDF does not have.
            FieldToLocate("BT-112", None, "5137.23", {"page": 3, "snippet": "5.137,23"}),
        ],
        INVOICE_TEXT,
    )
    iban = located[("BT-84", None)]
    assert iban.method == "evidence"
    # The box is the value inside the evidence, not the words "auf IBAN" before it.
    plain = _locate([FieldToLocate("BT-84", None, IBAN)], INVOICE_TEXT)[("BT-84", None)]
    assert iban.boxes == plain.boxes
    assert not located[("BT-13", None)].located
    assert not located[("BT-112", None)].located


def test_a_pdf_without_text_layer_has_no_pages_and_garbage_is_unreadable(
    samples: dict[str, bytes],
) -> None:
    assert [page.text.strip() for page in read_text_layer(samples["plain_pdf"])] == [""]
    with pytest.raises(UnreadablePdf):
        read_text_layer(b"%PDF-1.7 not really a pdf")


def test_endpoint_locates_the_fields_of_a_zugferd_pdf(
    client: TestClient, samples: dict[str, bytes]
) -> None:
    # The CII fixture's values, printed like an office program would.
    printed = [
        "Rechnung RE-2026-10417 vom 03.11.2026",
        "Gesamtbetrag 436,14 EUR",
        "IBAN DE17 1234 5678 0000 0000 01",
    ]
    pdf = generate_from_binary(text_pdf(printed), samples["cii_xrechnung"], check_xsd=False)
    response = client.post("/invoices", files={"file": ("zugferd.pdf", pdf, "application/pdf")})
    assert response.status_code == 202, response.text
    detail = poll_until_done(client, response.headers["location"])
    answer = client.get(f"/invoices/{detail['id']}/locations")
    assert answer.status_code == 200
    body = answer.json()
    assert body["pdf"] is True
    assert [(f["code"], f["line_no"]) for f in body["fields"]] == [
        (f["code"], f["line_no"]) for f in detail["fields"]
    ]
    by_code = {f["code"]: f for f in body["fields"] if f["line_no"] is None}
    for code in ("BT-1", "BT-2", "BT-112", "BT-84"):
        assert by_code[code]["located"], code
        assert by_code[code]["method"] == "text"
        assert by_code[code]["boxes"][0]["page"] == 1
    assert not by_code["BT-27"]["located"]
    assert by_code["BT-27"]["boxes"] == []


def test_endpoint_has_no_pdf_for_an_xml_invoice(
    client: TestClient, samples: dict[str, bytes]
) -> None:
    xml = samples["ubl_xrechnung"]
    upload = client.post("/invoices", files={"file": ("rechnung.xml", xml, "application/xml")})
    assert upload.status_code == 202, upload.text
    response = client.get(f"/invoices/{upload.json()['id']}/locations")
    assert response.status_code == 200
    assert response.json() == {"pdf": False, "fields": []}


def test_endpoint_needs_a_known_invoice_and_a_login(client: TestClient) -> None:
    assert client.get(f"/invoices/{uuid.uuid4()}/locations").status_code == 404
    client.cookies.clear()
    assert client.get(f"/invoices/{uuid.uuid4()}/locations").status_code == 401
