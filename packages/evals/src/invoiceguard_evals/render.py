"""Render an `InvoiceSpec` as a German PDF invoice with reportlab.

Three layouts and three built-in fonts give the model different pictures of the same terms.
`invariant=1` makes the output byte-identical between runs, so the committed PDFs (and the
recorded replies keyed by their hash) stay valid until a spec or this file changes.
"""

import io
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm as reportlab_mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

from invoiceguard_evals.specs import BUYER, ConflictKind, InvoiceSpec, Line

# reportlab is untyped: name its constants as floats once.
mm = float(reportlab_mm)
WIDTH, HEIGHT = float(A4[0]), float(A4[1])
LEFT = 22 * mm
RIGHT = WIDTH - 18 * mm
UNITS = {"C62": "Stk", "HUR": "Std", "MON": "Monat", "DAY": "Tag", "KGM": "kg"}
BOLD = {"Helvetica": "Helvetica-Bold", "Times-Roman": "Times-Bold", "Courier": "Courier-Bold"}
TABLE_SIZE = 8.5
ROW_GAP = 4.2 * mm
# Lines per page before the table continues on the next page.
FIRST_PAGE_ROWS = 18
NEXT_PAGE_ROWS = 34
# Column x positions: position, description, quantity, unit, unit price, VAT, amount.
COLUMNS = (LEFT, LEFT + 10 * mm, 114 * mm, 118 * mm, 154 * mm, 168 * mm, RIGHT)
DESCRIPTION_WIDTH = COLUMNS[2] - COLUMNS[1] - 16 * mm


def money(amount: Decimal) -> str:
    """German format: 1.234,50."""
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def number(value: Decimal) -> str:
    return f"{value.normalize():f}".replace(".", ",")


def day(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def grouped_iban(iban: str) -> str:
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


class _Page:
    def __init__(self, canvas: Canvas, spec: InvoiceSpec) -> None:
        self.canvas = canvas
        self.spec = spec
        self.regular = spec.font
        self.bold = BOLD[spec.font]

    def text(self, x: float, y: float, value: str, size: float = 9, bold: bool = False) -> None:
        self.canvas.setFont(self.bold if bold else self.regular, size)
        self.canvas.drawString(x, y, value)

    def right(self, x: float, y: float, value: str, size: float = 9, bold: bool = False) -> None:
        self.canvas.setFont(self.bold if bold else self.regular, size)
        self.canvas.drawRightString(x, y, value)


def _decoy(spec: InvoiceSpec, kind: ConflictKind) -> str | None:
    return next((c.decoy for c in spec.conflicts if c.kind == kind), None)


def _header(page: _Page) -> float:
    """Seller, addresses and the invoice data block; returns the y where the table starts."""
    spec, canvas = page.spec, page.canvas
    seller = spec.seller
    top = HEIGHT - 20 * mm
    if spec.layout == "band":
        canvas.setFillColorRGB(0.13, 0.27, 0.45)
        canvas.rect(0, HEIGHT - 32 * mm, WIDTH, 32 * mm, stroke=0, fill=1)
        canvas.setFillColorRGB(1, 1, 1)
        page.text(LEFT, top - 4 * mm, seller.name, 17, bold=True)
        page.text(LEFT, top - 10 * mm, f"{seller.street} · {seller.postal_code} {seller.city}", 9)
        canvas.setFillColorRGB(0, 0, 0)
    elif spec.layout == "compact":
        page.right(RIGHT, top, seller.name, 14, bold=True)
        page.right(RIGHT, top - 5 * mm, f"{seller.street}, {seller.postal_code} {seller.city}", 8)
        page.right(RIGHT, top - 9 * mm, seller.email, 8)
    else:
        page.text(LEFT, top, seller.name, 15, bold=True)
        page.text(LEFT, top - 5 * mm, f"{seller.street} · {seller.postal_code} {seller.city}", 9)

    letter_date = _decoy(spec, "delivery_date")
    if letter_date is not None:
        page.right(
            RIGHT, HEIGHT - 40 * mm, f"{seller.city}, {day(date.fromisoformat(letter_date))}"
        )

    address_top = HEIGHT - 52 * mm
    page.text(LEFT, address_top + 6 * mm, f"{seller.name} · {seller.street} · {seller.city}", 6.5)
    for n, value in enumerate(
        (BUYER.name, "Kreditorenbuchhaltung", BUYER.street, f"{BUYER.postal_code} {BUYER.city}")
    ):
        page.text(LEFT, address_top - n * 4.6 * mm, value, 10)

    info = [
        ("Rechnungsnummer", spec.number),
        ("Rechnungsdatum", day(spec.issue_date)),
        ("Lieferdatum", day(spec.delivery_date)),
    ]
    if spec.order_reference is not None:
        info.append(("Bestellnummer", spec.order_reference))
    info.append(("Ihre USt-IdNr.", BUYER.vat_id))
    label_x = 128 * mm
    for n, (label, value) in enumerate(info):
        y = address_top - n * 4.6 * mm
        page.text(label_x, y, label, 8.5)
        page.right(RIGHT, y, value, 8.5, bold=label == "Rechnungsnummer")

    header_total = _decoy(spec, "header_total")
    if header_total is not None:
        y = address_top - len(info) * 4.6 * mm - 3 * mm
        page.canvas.rect(label_x - 2 * mm, y - 2 * mm, RIGHT - label_x + 2 * mm, 7 * mm)
        page.text(label_x, y, "Rechnungsbetrag", 9, bold=True)
        page.right(RIGHT - 1 * mm, y, f"{money(Decimal(header_total))} €", 9, bold=True)

    title_y = HEIGHT - 98 * mm
    page.text(LEFT, title_y, f"Rechnung Nr. {spec.number}", 13, bold=True)
    page.text(LEFT, title_y - 7 * mm, "Sehr geehrte Damen und Herren,", 9.5)
    page.text(
        LEFT, title_y - 12 * mm, "wir berechnen Ihnen unsere Lieferungen und Leistungen:", 9.5
    )
    return title_y - 22 * mm


def _table_header(page: _Page, y: float) -> float:
    labels = ("Pos.", "Beschreibung", "Menge", "Einheit", "Einzelpreis €", "USt", "Betrag €")
    for n, label in enumerate(labels):
        if n in (0, 1, 3):
            page.text(COLUMNS[n], y, label, TABLE_SIZE, bold=True)
        else:
            page.right(COLUMNS[n], y, label, TABLE_SIZE, bold=True)
    page.canvas.line(LEFT, y - 1.6 * mm, RIGHT, y - 1.6 * mm)
    return y - ROW_GAP - 1 * mm


def _row(page: _Page, y: float, position: int, line: Line) -> float:
    description: list[str] = simpleSplit(
        line.description, page.regular, TABLE_SIZE, DESCRIPTION_WIDTH
    )
    page.text(COLUMNS[0], y, str(position), TABLE_SIZE)
    for n, part in enumerate(description):
        page.text(COLUMNS[1], y - n * 3.6 * mm, part, TABLE_SIZE)
    page.right(COLUMNS[2], y, number(line.quantity), TABLE_SIZE)
    page.text(COLUMNS[3], y, UNITS.get(line.unit_code, line.unit_code), TABLE_SIZE)
    page.right(COLUMNS[4], y, money(line.price), TABLE_SIZE)
    page.right(COLUMNS[5], y, f"{number(line.vat_rate)} %", TABLE_SIZE)
    page.right(COLUMNS[6], y, money(line.net), TABLE_SIZE)
    return y - ROW_GAP - (len(description) - 1) * 3.6 * mm


def _totals(page: _Page, y: float) -> float:
    spec = page.spec
    page.canvas.line(118 * mm, y + 4 * mm, RIGHT, y + 4 * mm)
    rows: list[tuple[str, Decimal, bool]] = [("Summe Positionen", spec.line_total, False)]
    if spec.allowance_total is not None:
        rows.append((f"abzgl. Rabatt {number(spec.discount_percent or Decimal(0))} %",
                     -spec.allowance_total, False))  # fmt: skip
        rows.append(("Nettobetrag", spec.net_total, False))
    rows += [
        (f"zzgl. USt {number(rate)} % auf {money(taxable)}", tax, False)
        for rate, taxable, tax in spec.vat_breakdown()
    ]
    rows.append(("Rechnungsbetrag", spec.gross_total, True))
    for label, amount, bold in rows:
        page.text(118 * mm, y, label, 9, bold=bold)
        page.right(RIGHT, y, f"{money(amount)} €", 9, bold=bold)
        y -= ROW_GAP + 0.6 * mm
    return y


def _closing(page: _Page, y: float) -> None:
    spec = page.spec
    y -= 4 * mm
    note = _decoy(spec, "order_note")
    if note is not None:
        page.text(LEFT, y, f"Hinweis: Rechnung gemäß Ihrer Bestellung Nr. {note} vom "
                  f"{day(spec.issue_date.replace(day=1))}.", 9)  # fmt: skip
        y -= 6 * mm
    terms = (
        "Zahlbar sofort ohne Abzug."
        if spec.due_date is None
        else f"Zahlbar ohne Abzug bis {day(spec.due_date)}."
    )
    page.text(LEFT, y, terms, 9.5)
    page.text(
        LEFT,
        y - 5 * mm,
        f"Bitte überweisen Sie den Rechnungsbetrag auf IBAN {grouped_iban(spec.iban)}.",
        9.5,
    )
    page.text(LEFT, y - 12 * mm, "Vielen Dank für Ihren Auftrag.", 9.5)
    _attack(page, y - 20 * mm)


def _attack(page: _Page, y: float) -> None:
    """An attack printed on the page (`attacks.py`): a visible footnote, the same in white on
    white, or at 1 pt. The text layer holds it either way; a reader of the page sees only the
    first."""
    attack = page.spec.attack
    if attack is None or attack.place not in ("pdf_visible", "pdf_white", "pdf_tiny"):
        return
    size = 1.0 if attack.place == "pdf_tiny" else 7.5
    if attack.place == "pdf_white":
        page.canvas.setFillColorRGB(1, 1, 1)
    parts: list[str] = simpleSplit(attack.text, page.regular, size, RIGHT - LEFT)
    for n, part in enumerate(parts):
        page.text(LEFT, y - n * size * 1.3, part, size)
    page.canvas.setFillColorRGB(0, 0, 0)


def _footer(page: _Page, number_: int, pages: int) -> None:
    spec, seller = page.spec, page.spec.seller
    footer_iban = _decoy(spec, "footer_iban") or spec.iban
    page.canvas.line(LEFT, 24 * mm, RIGHT, 24 * mm)
    columns = (
        (seller.name, seller.street, f"{seller.postal_code} {seller.city}"),
        (f"USt-IdNr.: {seller.vat_id}", f"E-Mail: {seller.email}", "Amtsgericht (Demo)"),
        ("Bankverbindung: Demo Bank", f"IBAN: {grouped_iban(footer_iban)}", "BIC: DEMODEFFXXX"),
    )
    for n, column in enumerate(columns):
        for k, value in enumerate(column):
            page.text(LEFT + n * 58 * mm, 20 * mm - k * 3.3 * mm, value, 7)
    page.right(RIGHT, 10 * mm, f"Seite {number_} von {pages}", 7)


def _pages(lines: Sequence[Line]) -> list[Sequence[Line]]:
    chunks = [lines[:FIRST_PAGE_ROWS]]
    rest = lines[FIRST_PAGE_ROWS:]
    while rest:
        chunks.append(rest[:NEXT_PAGE_ROWS])
        rest = rest[NEXT_PAGE_ROWS:]
    return chunks


def render(spec: InvoiceSpec) -> bytes:
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1, pageCompression=1)
    canvas.setTitle(f"Rechnung {spec.number}")
    canvas.setAuthor(spec.seller.name)
    page = _Page(canvas, spec)
    chunks = _pages(spec.lines)
    position = 1
    for n, chunk in enumerate(chunks, start=1):
        y = _header(page) if n == 1 else HEIGHT - 25 * mm
        if n > 1:
            page.text(LEFT, y + 8 * mm, f"Rechnung Nr. {spec.number} (Fortsetzung)", 10, True)
        y = _table_header(page, y)
        for line in chunk:
            y = _row(page, y, position, line)
            position += 1
        if n == len(chunks):
            _closing(page, _totals(page, y - 2 * mm))
        else:
            page.right(RIGHT, y - 2 * mm, "Fortsetzung auf der nächsten Seite", 8)
        _footer(page, n, len(chunks))
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()
