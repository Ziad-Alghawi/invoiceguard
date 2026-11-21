"""DATEV-style booking file ("Buchungsstapel", EXTF format 700, version 13), see ADR-013.

Pure functions, no database: the export endpoint (exports.py) turns approved invoices into
`Booking` rows (one per account and VAT rate with `split_by_account`, else one per invoice) and
writes them with `build_csv`. This follows DATEV's public format description; it
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
from collections import defaultdict
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
    """One booking row: a whole invoice, or its lines with one account and VAT rate."""

    # The gross amount of the row; the invoice's gross total (BT-112) when it has one row.
    gross_total: Decimal
    # Gegenkonto: the account the reviewer chose for the lines, or the configured expense account.
    account: str
    # A credit note reverses the direction of the booking.
    credit_note: bool
    currency: str
    document_date: date
    invoice_number: str
    seller_name: str
    # None when the row has no single VAT rate with a configured key (ADR-013).
    tax_key: str | None


@dataclass(frozen=True)
class Line:
    """One invoice line as the split needs it."""

    account: str
    # BT-131, net of line allowances and charges.
    net_amount: Decimal
    # BT-152 in percent; None for a line without a rate (for example exempt).
    vat_rate: Decimal | None


@dataclass(frozen=True)
class Totals:
    """The document totals the split must add up to."""

    net_total: Decimal  # BT-109
    tax_total: Decimal  # BT-110, zero when the invoice states none
    gross_total: Decimal  # BT-112
    # BT-107 or BT-108 not zero: a document allowance or charge belongs to no single line.
    allowances_or_charges: bool


@dataclass(frozen=True)
class Part:
    """The gross amount of an invoice's lines with one account and one VAT rate."""

    account: str
    vat_rate: Decimal | None
    gross: Decimal


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


def fiscal_year_start(day: date, start_month: int) -> date:
    """First day of the fiscal year that contains `day`."""
    year = day.year if day.month >= start_month else day.year - 1
    return date(year, start_month, 1)


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def split_by_account(lines: Sequence[Line], totals: Totals) -> list[Part] | None:
    """One part per (account, VAT rate), or None when the parts would not add up to the invoice.

    The tax is computed per rate on the sum of its lines, as EN 16931 computes BT-117, so a rate
    split over several accounts adds up exactly: the rounding cent goes to its largest part. The
    split is used only when the line nets equal BT-109 with no document allowance or charge, the
    taxes equal BT-110 and the gross amounts equal BT-112; otherwise the invoice keeps one row.
    """
    if not lines or totals.allowances_or_charges:
        return None
    nets: dict[Decimal | None, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for line in lines:
        nets[line.vat_rate][line.account] += line.net_amount
    parts: list[Part] = []
    tax_total = Decimal(0)
    for rate, by_account in nets.items():
        net = sum(by_account.values(), Decimal(0))
        share = rate / 100 if rate is not None else Decimal(0)
        tax = cents(net * share)
        tax_total += tax
        factor = 1 + share
        gross = {account: cents(value * factor) for account, value in by_account.items()}
        largest = max(sorted(gross), key=lambda account: abs(gross[account]))
        gross[largest] += net + tax - sum(gross.values(), Decimal(0))
        parts.extend(Part(account, rate, value) for account, value in gross.items())
    line_net = sum((line.net_amount for line in lines), Decimal(0))
    gross_total = sum((part.gross for part in parts), Decimal(0))
    if (line_net, tax_total, gross_total) != (
        totals.net_total,
        totals.tax_total,
        totals.gross_total,
    ):
        return None
    # The rows of an account together, rates ascending, a line without a rate last.
    return sorted(parts, key=lambda part: (part.account, part.vat_rate is None, part.vat_rate or 0))


def amount(value: Decimal) -> str:
    """1234.5 -> "1234,50": two decimals (half up), decimal comma, no sign, no grouping."""
    return f"{cents(abs(value)):f}".replace(".", ",")


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
    note; a negative amount (a negative total, or a row of discount lines) turns the direction
    around once more."""
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
        "Gegenkonto (ohne BU-Schlüssel)": booking.account,
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
