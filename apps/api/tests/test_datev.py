"""DATEV-style booking file (ADR-013): field formatting and one complete file (golden file)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from invoiceguard_api import datev

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "datev" / "EXTF_Buchungsstapel_golden.csv"


def booking(**changes: object) -> datev.Booking:
    values: dict[str, object] = {
        "gross_total": Decimal("5137.23"),
        "credit_note": False,
        "currency": "EUR",
        "document_date": date(2026, 11, 5),
        "invoice_number": "2026-IT-0815",
        "seller_name": "Demo IT-Service GmbH",
        "tax_key": "9",
    }
    values.update(changes)
    return datev.Booking(**values)  # type: ignore[arg-type]


BATCH = datev.Batch(
    created_at=datetime(2026, 11, 14, 9, 30, 15, 123456, tzinfo=UTC),
    exported_by="Anna Becker",
    advisor_number=1001,
    client_number=1,
    fiscal_year_start=date(2026, 1, 1),
    account_length=4,
    date_from=date(2026, 3, 1),
    date_to=date(2026, 11, 5),
    description="InvoiceGuard 2026-11-14",
    chart_of_accounts="03",
    creditor_account="70000",
    expense_account="4900",
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("5137.23"), "5137,23"),
        (Decimal("1234567.5"), "1234567,50"),
        (Decimal("0.005"), "0,01"),  # half up, not banker's rounding
        (Decimal("0.004"), "0,00"),
        (Decimal("-119.00"), "119,00"),  # no sign: Soll/Haben carries it
        (Decimal("1E+3"), "1000,00"),  # never scientific notation
    ],
)
def test_amount_has_a_decimal_comma_two_decimals_and_no_sign(value: Decimal, expected: str) -> None:
    assert datev.amount(value) == expected


def test_dates_are_ddmm_in_rows_and_yyyymmdd_in_the_header() -> None:
    assert datev.day_month(date(2026, 3, 1)) == "0103"
    assert datev.full_date(date(2026, 3, 1)) == "20260301"
    assert datev.timestamp(datetime(2026, 1, 2, 3, 4, 5, 6789)) == "20260102030405006"


def test_text_is_quoted_with_doubled_quotes_and_one_line() -> None:
    assert datev.text('Müller "Bau" GmbH') == '"Müller ""Bau"" GmbH"'
    assert datev.text("Zeile 1\r\nZeile 2;\t Ende") == '"Zeile 1 Zeile 2; Ende"'
    assert datev.text("a" * 70, 60) == '"' + "a" * 60 + '"'


def test_document_field_keeps_only_allowed_characters_and_36_of_them() -> None:
    assert datev.document_field("RE 2026.001:ä") == '"RE-2026-001--"'
    assert datev.document_field("A/B-1$%&*+") == '"A/B-1$%&*+"'
    assert datev.document_field("x" * 40) == '"' + "x" * 36 + '"'


@pytest.mark.parametrize(
    ("credit_note", "gross", "expected"),
    [
        (False, "119.00", "H"),  # invoice: creditor credited, expense debited
        (True, "119.00", "S"),  # credit note: the other way round
        (False, "-119.00", "S"),  # negative invoice total, same as a credit note
        (True, "-119.00", "H"),
    ],
)
def test_direction(credit_note: bool, gross: str, expected: str) -> None:
    assert datev.direction(booking(credit_note=credit_note, gross_total=Decimal(gross))) == expected


@pytest.mark.parametrize(
    ("day", "start_month", "expected"),
    [
        (date(2026, 11, 5), 1, date(2026, 1, 1)),
        (date(2026, 3, 31), 4, date(2025, 4, 1)),
        (date(2026, 4, 1), 4, date(2026, 4, 1)),
    ],
)
def test_fiscal_year_start(day: date, start_month: int, expected: date) -> None:
    assert datev.fiscal_year_start(day, start_month) == expected


def test_there_are_125_columns_and_every_row_has_them() -> None:
    assert len(datev.COLUMNS) == 125
    assert len(set(datev.COLUMNS)) == 125
    rows = datev.build_csv(BATCH, [booking()]).decode(datev.ENCODING).split("\r\n")
    assert len(rows[0].split(";")) == 31
    assert [len(row.split(";")) for row in rows[1:3]] == [125, 125]
    assert rows[3] == ""


def test_the_file_is_windows_1252_with_umlauts() -> None:
    content = datev.build_csv(BATCH, [booking(seller_name="Bäckerei Groß & Söhne")])
    assert "Bäckerei Groß & Söhne".encode("cp1252") in content
    assert "Bäckerei".encode() not in content  # not UTF-8


def test_characters_outside_windows_1252_become_a_question_mark() -> None:
    content = datev.build_csv(BATCH, [booking(seller_name="Łódź Sp. z o.o.")])
    assert b'"?\xf3d? Sp. z o.o."' in content


def test_golden_file() -> None:
    """One complete file, byte for byte. Rebuild it only after checking the change by hand."""
    bookings = [
        booking(document_date=date(2026, 3, 1)),
        booking(
            gross_total=Decimal("107.00"),
            invoice_number="GS 2026.17",
            seller_name='Bäckerei "Groß" & Söhne',
            tax_key="8",
            credit_note=True,
            document_date=date(2026, 6, 30),
        ),
        booking(gross_total=Decimal("226.10"), tax_key=None),
    ]
    assert datev.build_csv(BATCH, bookings) == GOLDEN.read_bytes()
