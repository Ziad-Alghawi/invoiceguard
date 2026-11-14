"""DATEV-style booking file ("Buchungsstapel", EXTF format 700, version 13), see ADR-013.

Pure formatting, no database: the export endpoint (exports.py) turns approved invoices into
`Booking`s and writes them with `build_csv`. This follows DATEV's public format description; it
is not a certified DATEV interface, and the result must be checked by the tax advisor's import.

Format rules applied here:
- Row 1 is the EXTF header, row 2 the column names, then one row per booking.
- Fields are separated by `;`, text fields are in double quotes (a quote inside is doubled),
  numbers are not quoted, rows end with CRLF, the file is Windows-1252 (ANSI).
- Amounts have a decimal comma, two decimals, no thousands separator and no sign: the
  Soll/Haben flag carries the direction.
- Belegdatum is DDMM; the year comes from the header's date range, so one file holds one
  fiscal year only.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

ENCODING = "cp1252"
SEPARATOR = ";"
LINE_END = "\r\n"

# Header constants (format description, "Header").
MARKER = "EXTF"  # Export from a third-party application (DATEV's own exports say DTVF).
HEADER_VERSION = 700
CATEGORY_BOOKINGS = 21
FORMAT_NAME = "Buchungsstapel"
FORMAT_VERSION = 13
SOURCE = "RE"  # Herkunft: two letters naming the source; "RE" for Rechnungseingang.
BOOKING_TYPE_FINANCIAL = 1  # Buchungstyp 1 = Finanzbuchführung.
ACCOUNTING_PURPOSE = 0  # Rechnungslegungszweck 0 = independent of the purpose.
NOT_FIXED = 0  # Festschreibung 0: the advisor can still change the bookings after import.
HEADER_CURRENCY = "EUR"

# Field lengths (format description, "Buchungsstapel").
DESCRIPTION_MAX = 30
EXPORTED_BY_MAX = 25
DOCUMENT_FIELD_MAX = 36
BOOKING_TEXT_MAX = 60

# Belegfeld 1 is the key for open items; DATEV refuses spaces, umlauts, dots, commas, semicolons
# and colons in it. Only these characters are kept; any other becomes "-".
DOCUMENT_FIELD_ALLOWED = re.compile(r"[^A-Za-z0-9$%&*+\-/]")

DEBIT = "S"  # Soll: the Konto is debited, the Gegenkonto credited.
CREDIT = "H"  # Haben: the Konto is credited, the Gegenkonto debited.

CENT = Decimal("0.01")

# The 125 columns of the Buchungsstapel in format version 13, in order. DATEV reads the
# columns by position, so all are written, most of them empty.
COLUMNS: tuple[str, ...] = (
    "Umsatz (ohne Soll/Haben-Kz)",
    "Soll/Haben-Kennzeichen",
    "WKZ Umsatz",
    "Kurs",
    "Basis-Umsatz",
    "WKZ Basis-Umsatz",
    "Konto",
    "Gegenkonto (ohne BU-Schlüssel)",
    "BU-Schlüssel",
    "Belegdatum",
    "Belegfeld 1",
    "Belegfeld 2",
    "Skonto",
    "Buchungstext",
    "Postensperre",
    "Diverse Adressnummer",
    "Geschäftspartnerbank",
    "Sachverhalt",
    "Zinssperre",
    "Beleglink",
    *(f"Beleginfo - {part} {n}" for n in range(1, 9) for part in ("Art", "Inhalt")),
    "KOST1 - Kostenstelle",
    "KOST2 - Kostenstelle",
    "Kost-Menge",
    "EU-Land u. UStID (Bestimmung)",
    "EU-Steuersatz (Bestimmung)",
    "Abw. Versteuerungsart",
    "Sachverhalt L+L",
    "Funktionsergänzung L+L",
    "BU 49 Hauptfunktionstyp",
    "BU 49 Hauptfunktionsnummer",
    "BU 49 Funktionsergänzung",
    *(f"Zusatzinformation - {part} {n}" for n in range(1, 21) for part in ("Art", "Inhalt")),
    "Stück",
    "Gewicht",
    "Zahlweise",
    "Forderungsart",
    "Veranlagungsjahr",
    "Zugeordnete Fälligkeit",
    "Skontotyp",
    "Auftragsnummer",
    "Buchungstyp",
    "USt-Schlüssel (Anzahlungen)",
    "EU-Land (Anzahlungen)",
    "Sachverhalt L+L (Anzahlungen)",
    "EU-Steuersatz (Anzahlungen)",
    "Erlöskonto (Anzahlungen)",
    "Herkunft-Kz",
    "Buchungs GUID",
    "KOST-Datum",
    "SEPA-Mandatsreferenz",
    "Skontosperre",
    "Gesellschaftername",
    "Beteiligtennummer",
    "Identifikationsnummer",
    "Zeichnernummer",
    "Postensperre bis",
    "Bezeichnung SoBil-Sachverhalt",
    "Kennzeichen SoBil-Buchung",
    "Festschreibung",
    "Leistungsdatum",
    "Datum Zuord. Steuerperiode",
    "Fälligkeit",
    "Generalumkehr (GU)",
    "Steuersatz",
    "Land",
    "Abrechnungsreferenz",
    "BVV-Position",
    "EU-Land u. UStID (Ursprung)",
    "EU-Steuersatz (Ursprung)",
    "Abw. Skontokonto",
)


@dataclass(frozen=True)
class Booking:
    """One approved invoice as one booking row."""

    # The gross total (BT-112) as on the invoice.
    gross_total: Decimal
    # A credit note reverses the direction of the booking.
    credit_note: bool
    currency: str
    document_date: date
    invoice_number: str
    seller_name: str
    # None when the invoice has no single VAT rate with a configured key (ADR-013).
    tax_key: str | None


@dataclass(frozen=True)
class Batch:
    """Header values of one file."""

    created_at: datetime
    exported_by: str
    advisor_number: int
    client_number: int
    fiscal_year_start: date
    account_length: int
    date_from: date
    date_to: date
    description: str
    chart_of_accounts: str
    creditor_account: str
    expense_account: str


def fiscal_year_start(day: date, start_month: int) -> date:
    """First day of the fiscal year that contains `day`."""
    year = day.year if day.month >= start_month else day.year - 1
    return date(year, start_month, 1)


def amount(value: Decimal) -> str:
    """1234.5 -> "1234,50": two decimals (half up), decimal comma, no sign, no grouping."""
    rounded = abs(value).quantize(CENT, rounding=ROUND_HALF_UP)
    return f"{rounded:f}".replace(".", ",")


def text(value: str, max_length: int | None = None) -> str:
    """A quoted text field: whitespace runs (also line breaks) become one space, quotes doubled."""
    cleaned = " ".join(value.split())
    if max_length is not None:
        cleaned = cleaned[:max_length]
    return '"' + cleaned.replace('"', '""') + '"'


def document_field(invoice_number: str) -> str:
    """Belegfeld 1: the invoice number with only allowed characters, at most 36."""
    return text(DOCUMENT_FIELD_ALLOWED.sub("-", invoice_number.strip()), DOCUMENT_FIELD_MAX)


def day_month(day: date) -> str:
    return day.strftime("%d%m")


def full_date(day: date) -> str:
    return day.strftime("%Y%m%d")


def timestamp(moment: datetime) -> str:
    """YYYYMMDDHHMMSSFFF, milliseconds included."""
    return moment.strftime("%Y%m%d%H%M%S") + f"{moment.microsecond // 1000:03d}"


def direction(booking: Booking) -> str:
    """The supplier's creditor account is credited for an invoice and debited for a credit
    note; a negative total turns the direction around once more."""
    reversed_ = booking.credit_note != (booking.gross_total < 0)
    return DEBIT if reversed_ else CREDIT


def header_row(batch: Batch) -> list[str]:
    return [
        text(MARKER),
        str(HEADER_VERSION),
        str(CATEGORY_BOOKINGS),
        text(FORMAT_NAME),
        str(FORMAT_VERSION),
        timestamp(batch.created_at),
        "",  # Importiert: set by DATEV.
        text(SOURCE),
        text(batch.exported_by, EXPORTED_BY_MAX),
        text(""),  # Importiert von: set by DATEV.
        str(batch.advisor_number),
        str(batch.client_number),
        full_date(batch.fiscal_year_start),
        str(batch.account_length),
        full_date(batch.date_from),
        full_date(batch.date_to),
        text(batch.description, DESCRIPTION_MAX),
        text(""),  # Diktatkürzel
        str(BOOKING_TYPE_FINANCIAL),
        str(ACCOUNTING_PURPOSE),
        str(NOT_FIXED),
        text(HEADER_CURRENCY),
        "",  # reserved
        text(""),  # Derivatskennzeichen
        "",  # reserved
        "",  # reserved
        text(batch.chart_of_accounts),
        "",  # Branchen-Lösungs-ID
        "",  # reserved
        text(""),  # reserved
        text(""),  # Anwendungsinformation
    ]


def booking_row(booking: Booking, batch: Batch) -> list[str]:
    values = {
        "Umsatz (ohne Soll/Haben-Kz)": amount(booking.gross_total),
        "Soll/Haben-Kennzeichen": text(direction(booking)),
        "WKZ Umsatz": text(booking.currency),
        "Konto": batch.creditor_account,
        "Gegenkonto (ohne BU-Schlüssel)": batch.expense_account,
        "BU-Schlüssel": text(booking.tax_key or ""),
        "Belegdatum": day_month(booking.document_date),
        "Belegfeld 1": document_field(booking.invoice_number),
        "Buchungstext": text(booking.seller_name, BOOKING_TEXT_MAX),
    }
    return [values.get(column, "") for column in COLUMNS]


def _lines(rows: Iterable[Sequence[str]]) -> str:
    return "".join(SEPARATOR.join(row) + LINE_END for row in rows)


def build_csv(batch: Batch, bookings: Sequence[Booking]) -> bytes:
    """The whole file; characters Windows-1252 cannot hold become "?"."""
    rows = [header_row(batch), list(COLUMNS), *(booking_row(b, batch) for b in bookings)]
    return _lines(rows).encode(ENCODING, errors="replace")
