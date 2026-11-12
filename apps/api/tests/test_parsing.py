import logging
import time
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from lxml import etree

from invoiceguard_api.models import SourceType
from invoiceguard_api.parsing import (
    InvalidInvoice,
    NoEmbeddedXml,
    ParsedInvoice,
    ParsedLine,
    UnsupportedFormat,
    VatBreakdown,
    parse_invoice,
    safe_xml,
)
from invoiceguard_api.parsing.fields import FieldRow, to_field_rows
from invoiceguard_api.parsing.safe_xml import parse_xml

PdfWithAttachment = Callable[[str, bytes], bytes]
BUYER = "Beispielkunde Handels GmbH"
BUYER_VAT_ID = "DE999000068"


def test_reads_xrechnung_cii(samples: dict[str, bytes]) -> None:
    invoice = parse_invoice(samples["cii_xrechnung"], SourceType.XML)

    assert invoice == ParsedInvoice(
        syntax="cii",
        invoice_number="RE-2026-10417",
        issue_date=date(2026, 11, 3),
        type_code="380",
        currency="EUR",
        due_date=date(2026, 12, 3),
        seller_name="Muster Bürobedarf GmbH",
        seller_vat_id="DE999000017",
        buyer_name=BUYER,
        buyer_vat_id=BUYER_VAT_ID,
        payee_iban="DE17123456780000000001",
        order_reference="PO-2026-0001",
        line_total=Decimal("366.50"),
        allowance_total=None,
        charge_total=None,
        net_total=Decimal("366.50"),
        tax_total=Decimal("69.64"),
        gross_total=Decimal("436.14"),
        amount_due=Decimal("436.14"),
        lines=(
            ParsedLine(
                line_id="1",
                item_name="Kopierpapier A4, 80 g/m², Karton à 2.500 Blatt",
                quantity=Decimal("10"),
                unit_code="C62",
                net_price=Decimal("24.90"),
                net_amount=Decimal("249.00"),
                vat_rate=Decimal("19"),
            ),
            ParsedLine(
                line_id="2",
                item_name="Ordner DIN A4, 8 cm, blau",
                quantity=Decimal("50"),
                unit_code="C62",
                net_price=Decimal("2.35"),
                net_amount=Decimal("117.50"),
                vat_rate=Decimal("19"),
            ),
        ),
        vat_breakdown=(
            VatBreakdown(
                category_code="S",
                rate=Decimal("19"),
                taxable_amount=Decimal("366.50"),
                tax_amount=Decimal("69.64"),
            ),
        ),
    )


def test_reads_xrechnung_ubl(samples: dict[str, bytes]) -> None:
    invoice = parse_invoice(samples["ubl_xrechnung"], SourceType.XML)

    assert invoice.syntax == "ubl"
    assert invoice.invoice_number == "2026-IT-0815"
    assert (invoice.issue_date, invoice.due_date) == (date(2026, 11, 5), date(2026, 11, 19))
    assert (invoice.seller_name, invoice.seller_vat_id) == ("Demo IT-Service GmbH", "DE999000033")
    assert (invoice.buyer_name, invoice.buyer_vat_id) == (BUYER, BUYER_VAT_ID)
    assert invoice.payee_iban == "DE60123456780000000003"
    totals = (invoice.net_total, invoice.tax_total, invoice.gross_total, invoice.amount_due)
    assert totals == (Decimal("4317.00"), Decimal("820.23"), Decimal("5137.23"), Decimal("5137.23"))
    assert [(line.line_id, line.unit_code, line.net_amount) for line in invoice.lines] == [
        ("1", "C62", Decimal("3747.00")),
        ("2", "HUR", Decimal("570.00")),
    ]
    assert invoice.order_reference == "PO-2026-0005"
    assert invoice.line_total == Decimal("4317.00")
    assert invoice.vat_breakdown == (
        VatBreakdown(
            category_code="S",
            rate=Decimal("19"),
            taxable_amount=Decimal("4317.00"),
            tax_amount=Decimal("820.23"),
        ),
    )
    assert invoice.warnings == ()


def test_reads_zugferd2_pdf_without_payee_iban(samples: dict[str, bytes]) -> None:
    invoice = parse_invoice(samples["zugferd2_pdf"], SourceType.PDF)

    assert invoice.syntax == "cii"
    assert invoice.invoice_number == "ED-77120"
    assert invoice.seller_name == "Exempel Druck & Medien GmbH"
    # Direct debit: the only IBAN is the buyer's (BT-91), which is not a payee IBAN.
    assert invoice.payee_iban is None
    assert invoice.buyer_vat_id is None
    assert invoice.gross_total == Decimal("266.97")
    assert [line.vat_rate for line in invoice.lines] == [Decimal("7")]
    assert invoice.order_reference == "PO-2026-0010"
    assert [(group.rate, group.tax_amount) for group in invoice.vat_breakdown] == [
        (Decimal("7"), Decimal("17.47"))
    ]


@pytest.mark.parametrize(
    ("sample", "source_type"),
    [("zugferd1", SourceType.XML), ("zugferd1_pdf", SourceType.PDF)],
)
def test_zugferd1_is_unsupported(
    samples: dict[str, bytes], sample: str, source_type: SourceType
) -> None:
    with pytest.raises(UnsupportedFormat, match=r"ZUGFeRD 1.0 is not supported"):
        parse_invoice(samples[sample], source_type)


@pytest.mark.parametrize(
    ("xml", "reason"),
    [
        (b'<Order xmlns="urn:example:order"/>', r"root element \{urn:example:order\}Order"),
        (b"<Rechnung/>", "root element Rechnung"),
        (
            b'<CreditNote xmlns="urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2"/>',
            "UBL credit notes are not supported",
        ),
    ],
)
def test_unknown_xml_is_unsupported(xml: bytes, reason: str) -> None:
    with pytest.raises(UnsupportedFormat, match=reason):
        parse_invoice(xml, SourceType.XML)


def test_broken_xml_is_invalid(samples: dict[str, bytes]) -> None:
    with pytest.raises(InvalidInvoice, match="not well-formed"):
        parse_invoice(samples["broken"], SourceType.XML)


def test_plain_pdf_has_no_embedded_xml(samples: dict[str, bytes]) -> None:
    with pytest.raises(NoEmbeddedXml):
        parse_invoice(samples["plain_pdf"], SourceType.PDF)


def test_unreadable_pdf_is_invalid() -> None:
    with pytest.raises(InvalidInvoice, match="PDF cannot be read"):
        parse_invoice(b"%PDF-1.7\nnot really a pdf\n", SourceType.PDF)


def test_pdf_with_unrelated_xml_attachment_counts_as_plain(
    pdf_with_attachment: PdfWithAttachment,
) -> None:
    pdf = pdf_with_attachment("lieferschein.xml", b"<Lieferschein/>")

    with pytest.raises(NoEmbeddedXml):
        parse_invoice(pdf, SourceType.PDF)


# --- XML attacks -----------------------------------------------------------------------------


def _xxe(target: str) -> bytes:
    return (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE r [<!ENTITY xxe SYSTEM "' + target.encode() + b'">]>\n'
        b"<r>&xxe;</r>"
    )


@pytest.fixture
def secret_file(tmp_path: Path) -> Path:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-7f3a")
    return secret


def test_xxe_fixture_is_rejected(samples: dict[str, bytes]) -> None:
    with pytest.raises(InvalidInvoice, match="document type declaration"):
        parse_invoice(samples["xxe"], SourceType.XML)


def test_xxe_cannot_read_a_local_file(secret_file: Path) -> None:
    with pytest.raises(InvalidInvoice) as raised:
        parse_xml(_xxe(secret_file.as_uri()))

    assert "TOP-SECRET" not in str(raised.value)


def test_hardened_parser_never_expands_entities(secret_file: Path) -> None:
    # Second line of defence: even without the DTD check, the entity stays unexpanded.
    root = etree.fromstring(_xxe(secret_file.as_uri()), safe_xml._parser())

    assert b"TOP-SECRET" not in etree.tostring(root)


def test_xxe_inside_a_pdf_attachment_leaks_nothing(
    secret_file: Path, pdf_with_attachment: PdfWithAttachment
) -> None:
    # factur-x parses the attachment with lxml's defaults, which refuse external entities;
    # the attachment is skipped, so the PDF goes the plain-PDF way and the secret stays unread.
    pdf = pdf_with_attachment("factur-x.xml", _xxe(secret_file.as_uri()))

    with pytest.raises(NoEmbeddedXml):
        parse_invoice(pdf, SourceType.PDF)


def test_billion_laughs_is_rejected_quickly(samples: dict[str, bytes]) -> None:
    started = time.perf_counter()

    with pytest.raises(InvalidInvoice):
        parse_invoice(samples["billion_laughs"], SourceType.XML)

    assert time.perf_counter() - started < 1


# --- Field rules -----------------------------------------------------------------------------

SECOND_PAYMENT_MEANS = b"""<cac:PaymentMeans>
    <cbc:PaymentMeansCode>58</cbc:PaymentMeansCode>
    <cac:PayeeFinancialAccount>
      <cbc:ID>DE02 1203 0000 0000 2020 51</cbc:ID>
    </cac:PayeeFinancialAccount>
  </cac:PaymentMeans>
  <cac:PaymentTerms>"""


def test_several_payee_ibans_keep_the_first_and_warn(
    samples: dict[str, bytes], caplog: pytest.LogCaptureFixture
) -> None:
    xml = samples["ubl_xrechnung"].replace(b"<cac:PaymentTerms>", SECOND_PAYMENT_MEANS)

    with caplog.at_level(logging.WARNING):
        invoice = parse_invoice(xml, SourceType.XML)

    assert invoice.payee_iban == "DE60123456780000000003"
    assert invoice.warnings == ("multiple_payee_ibans: 2 found, stored the first",)
    assert "2 different payee IBANs" in caplog.text
    # The IBANs themselves are personal data and stay out of the logs.
    assert "DE0212030000" not in caplog.text


def test_same_iban_twice_is_not_a_warning(samples: dict[str, bytes]) -> None:
    same = SECOND_PAYMENT_MEANS.replace(b"DE02 1203 0000 0000 2020 51", b"de60123456780000000003")
    xml = samples["ubl_xrechnung"].replace(b"<cac:PaymentTerms>", same)

    invoice = parse_invoice(xml, SourceType.XML)

    assert invoice.payee_iban == "DE60123456780000000003"
    assert invoice.warnings == ()


@pytest.mark.parametrize(
    ("sample", "old", "new", "reason"),
    [
        ("ubl_xrechnung", b"<cbc:ID>2026-IT-0815</cbc:ID>", b"", "BT-1 is missing"),
        ("ubl_xrechnung", b"5137.23</cbc:PayableAmount>", b"viel</cbc:PayableAmount>", "BT-115"),
        ("ubl_xrechnung", b"2026-11-05</cbc:IssueDate>", b"05.11.2026</cbc:IssueDate>", "BT-2"),
        ("ubl_xrechnung", b"<cbc:DueDate>2026-11-19", b"<cbc:DueDate>2026-13-19", "BT-9"),
        ("ubl_xrechnung", b'unitCode="HUR"', b"", "BT-130 is missing"),
        ("cii_xrechnung", b'format="102">20261103', b'format="610">202611', "only 102"),
        ("cii_xrechnung", b'format="102">20261103', b'format="102">20261332', "BT-2"),
        ("cii_xrechnung", b"<ram:GrandTotalAmount>436.14", b"<ram:GrandTotalAmount>NaN", "BT-112"),
        ("cii_xrechnung", b"<ram:Name>Ordner DIN A4, 8 cm, blau</ram:Name>", b"", "BT-153"),
    ],
)
def test_invalid_values_name_the_business_term(
    samples: dict[str, bytes], sample: str, old: bytes, new: bytes, reason: str
) -> None:
    assert old in samples[sample]
    xml = samples[sample].replace(old, new)

    with pytest.raises(InvalidInvoice, match=reason):
        parse_invoice(xml, SourceType.XML)


def test_tax_total_is_taken_in_the_invoice_currency(samples: dict[str, bytes]) -> None:
    # BT-111 (VAT in accounting currency) may come first; BT-110 is the one in BT-5.
    xml = samples["cii_xrechnung"].replace(
        b'<ram:TaxTotalAmount currencyID="EUR">',
        b'<ram:TaxTotalAmount currencyID="CHF">65.20</ram:TaxTotalAmount>'
        b'<ram:TaxTotalAmount currencyID="EUR">',
    )

    assert parse_invoice(xml, SourceType.XML).tax_total == Decimal("69.64")


def test_missing_optional_terms_are_none(samples: dict[str, bytes]) -> None:
    xml = (
        samples["ubl_xrechnung"]
        .replace(b"<cbc:DueDate>2026-11-19</cbc:DueDate>", b"")
        .replace(
            b'<cbc:TaxAmount currencyID="EUR">820.23</cbc:TaxAmount>\n    <cac:TaxSub',
            b"<cac:TaxSub",
        )
    )

    invoice = parse_invoice(xml, SourceType.XML)

    assert (invoice.due_date, invoice.tax_total) == (None, None)


def test_reads_document_allowances_and_charges(samples: dict[str, bytes]) -> None:
    xml = samples["ubl_xrechnung"].replace(
        b'<cbc:TaxExclusiveAmount currencyID="EUR">',
        b'<cbc:AllowanceTotalAmount currencyID="EUR">17.00</cbc:AllowanceTotalAmount>'
        b'<cbc:ChargeTotalAmount currencyID="EUR">5.00</cbc:ChargeTotalAmount>'
        b'<cbc:TaxExclusiveAmount currencyID="EUR">',
    )

    invoice = parse_invoice(xml, SourceType.XML)

    assert (invoice.allowance_total, invoice.charge_total) == (Decimal("17.00"), Decimal("5.00"))


def test_vat_breakdown_without_rate_has_rate_none(samples: dict[str, bytes]) -> None:
    xml = samples["cii_xrechnung"].replace(
        b"<ram:BasisAmount>366.50</ram:BasisAmount>\n"
        b"        <ram:CategoryCode>S</ram:CategoryCode>\n"
        b"        <ram:RateApplicablePercent>19</ram:RateApplicablePercent>",
        b"<ram:BasisAmount>366.50</ram:BasisAmount><ram:CategoryCode>O</ram:CategoryCode>",
    )

    (group,) = parse_invoice(xml, SourceType.XML).vat_breakdown

    assert (group.category_code, group.rate) == ("O", None)


# --- Business-term rows ----------------------------------------------------------------------


def test_field_rows_use_bt_codes_and_line_numbers(samples: dict[str, bytes]) -> None:
    rows = to_field_rows(parse_invoice(samples["cii_xrechnung"], SourceType.XML))

    assert FieldRow("BT-1", None, "RE-2026-10417") in rows
    assert FieldRow("BT-2", None, "2026-11-03") in rows
    assert FieldRow("BT-84", None, "DE17123456780000000001") in rows
    assert FieldRow("BT-109", None, "366.50") in rows
    assert FieldRow("BT-131", 2, "117.50") in rows
    assert FieldRow("BT-153", 1, "Kopierpapier A4, 80 g/m², Karton à 2.500 Blatt") in rows
    assert FieldRow("BT-13", None, "PO-2026-0001") in rows
    assert FieldRow("BT-106", None, "366.50") in rows
    # 16 document terms (no BT-107/BT-108 allowances or charges) and 7 per line.
    assert len(rows) == 16 + 2 * 7
    assert len({(row.code, row.line_no) for row in rows}) == len(rows)


def test_field_rows_leave_out_absent_terms(samples: dict[str, bytes]) -> None:
    rows = to_field_rows(parse_invoice(samples["zugferd2_pdf"], SourceType.PDF))

    codes = {row.code for row in rows}
    assert "BT-84" not in codes
    assert "BT-48" not in codes
    assert "BT-1" in codes
