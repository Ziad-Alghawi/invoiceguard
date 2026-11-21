"""DATEV-style booking file (ADR-013): field formatting, the split per account and VAT rate, and
complete files (golden files)."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from invoiceguard_api import datev

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "datev"
GOLDEN = FIXTURES / "EXTF_Buchungsstapel_golden.csv"
TAX_KEYS = {Decimal(19): "9", Decimal(7): "8"}


def booking(**changes: object) -> datev.Booking:
    values: dict[str, object] = {
        "gross_total": Decimal("5137.23"),
        "account": "4900",
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


def line(account: str, net: str, rate: str | None = "19") -> datev.Line:
    return datev.Line(account, Decimal(net), None if rate is None else Decimal(rate))


def totals(net: str, tax: str, gross: str, allowances_or_charges: bool = False) -> datev.Totals:
    return datev.Totals(Decimal(net), Decimal(tax), Decimal(gross), allowances_or_charges)


def parts(lines: list[datev.Line], invoice: datev.Totals) -> list[tuple[str, str | None, str]]:
    split = datev.split_by_account(lines, invoice)
    assert split is not None
    return [
        (p.account, None if p.vat_rate is None else str(p.vat_rate), str(p.gross)) for p in split
    ]


def test_lines_with_one_account_and_rate_are_one_part() -> None:
    lines = [line("0410", "3747.00"), line("0410", "570.00")]

    assert parts(lines, totals("4317.00", "820.23", "5137.23")) == [("0410", "19", "5137.23")]


def test_one_part_per_account_and_rate() -> None:
    lines = [line("4930", "100.00"), line("4930", "50.00", "7"), line("4806", "33.33")]

    assert parts(lines, totals("183.33", "28.83", "212.16")) == [
        ("4806", "19", "39.66"),
        ("4930", "7", "53.50"),
        ("4930", "19", "119.00"),
    ]


def test_the_rounding_cent_of_a_rate_goes_to_its_largest_part() -> None:
    # 19 % of 0.06 is 0.01, so the rate's gross is 0.07, while each account alone rounds to
    # 0.04. The cent comes off the largest part; on a tie, the first account.
    lines = [line("4930", "0.03"), line("4806", "0.02"), line("4806", "0.01")]

    assert parts(lines, totals("0.06", "0.01", "0.07")) == [
        ("4806", "19", "0.03"),
        ("4930", "19", "0.04"),
    ]


def test_the_tax_is_rounded_per_rate_not_per_line() -> None:
    # Per line 19 % of 0.05 rounds to 0.01 twice; on the rate's 0.10 it is 0.02 (BT-117).
    lines = [line("4930", "0.05"), line("4930", "0.05")]

    assert parts(lines, totals("0.10", "0.02", "0.12")) == [("4930", "19", "0.12")]
    assert datev.split_by_account(lines, totals("0.10", "0.01", "0.11")) is None


def test_a_line_without_a_rate_is_a_part_without_tax() -> None:
    lines = [line("4930", "100.00"), line("4970", "15.00", None)]

    assert parts(lines, totals("115.00", "19.00", "134.00")) == [
        ("4930", "19", "119.00"),
        ("4970", None, "15.00"),
    ]


def test_rates_written_differently_are_one_rate() -> None:
    lines = [line("4930", "10.00", "7.00"), line("4930", "10.00", "7")]

    assert parts(lines, totals("20.00", "1.40", "21.40")) == [("4930", "7.00", "21.40")]


def test_a_discount_line_can_be_a_negative_part() -> None:
    lines = [line("0410", "1000.00"), line("4730", "-50.00")]

    split = parts(lines, totals("950.00", "180.50", "1130.50"))

    assert split == [("0410", "19", "1190.00"), ("4730", "19", "-59.50")]


@pytest.mark.parametrize(
    "invoice",
    [
        totals("4317.00", "820.23", "5137.23", allowances_or_charges=True),
        totals("4300.00", "817.00", "5117.00"),  # line nets are not BT-109
        totals("4317.00", "820.24", "5137.24"),  # tax is not BT-110
        totals("4317.00", "820.23", "5137.24"),  # gross is not BT-112
    ],
    ids=["allowance-or-charge", "net", "tax", "gross"],
)
def test_no_split_when_the_parts_do_not_add_up(invoice: datev.Totals) -> None:
    lines = [line("0410", "3747.00"), line("4806", "570.00")]

    assert datev.split_by_account(lines, invoice) is None


def test_no_split_without_lines() -> None:
    assert datev.split_by_account([], totals("0", "0", "0")) is None


def split_bookings(
    lines: list[datev.Line], invoice: datev.Totals, **changes: object
) -> list[datev.Booking]:
    """The rows of one invoice as the export builds them from its split."""
    split = datev.split_by_account(lines, invoice)
    assert split is not None
    return [
        booking(
            gross_total=part.gross,
            account=part.account,
            tax_key=None if part.vat_rate is None else TAX_KEYS.get(part.vat_rate),
            **changes,
        )
        for part in split
    ]


IT_SERVICE = totals("4317.00", "820.23", "5137.23")
OFFICE = {
    "invoice_number": "BB-2026-311",
    "seller_name": "Müller Bürobedarf GmbH",
    "document_date": date(2026, 10, 20),
}
GOLDEN_SPLITS: dict[str, tuple[list[datev.Line], datev.Totals, dict[str, object]]] = {
    "one_account": ([line("0410", "3747.00"), line("0410", "570.00")], IT_SERVICE, {}),
    "two_accounts": ([line("0410", "3747.00"), line("4806", "570.00")], IT_SERVICE, {}),
    "two_vat_rates": (
        [line("4930", "100.00"), line("4930", "50.00", "7"), line("4806", "33.33")],
        totals("183.33", "28.83", "212.16"),
        OFFICE,
    ),
}


@pytest.mark.parametrize("name", list(GOLDEN_SPLITS))
def test_golden_file_per_account(name: str) -> None:
    """Files from chosen accounts, byte for byte (issue #24). Rebuild one only after checking the
    change by hand."""
    lines, invoice, changes = GOLDEN_SPLITS[name]
    rows = split_bookings(lines, invoice, **changes)
    golden = FIXTURES / f"EXTF_Buchungsstapel_{name}.csv"
    assert datev.build_csv(BATCH, rows) == golden.read_bytes()
