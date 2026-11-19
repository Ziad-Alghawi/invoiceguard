"""Invoice specs: one spec renders as a PDF (`render.py`) and as UBL XML (`ubl.py`), and gives
the ground truth (`truth`) for both, so the truth never comes from a model.

Suppliers, verified IBANs and orders come from the demo seed (`invoiceguard_api.seed`), so the
checks see the same master data in the eval as on the demo.
"""

from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from invoiceguard_api.parsing import ParsedInvoice
from invoiceguard_api.seed import ORDERS, SUPPLIERS, OrderSeed, SupplierSeed

CENT = Decimal("0.01")
Layout = Literal["classic", "band", "compact"]
Font = Literal["Helvetica", "Times-Roman", "Courier"]
# Where a conflicting value is printed next to the right one (see `Conflict`).
ConflictKind = Literal["order_note", "footer_iban", "header_total", "delivery_date"]
# Where an attack puts its text (`attacks.py`): printed on the PDF (visible, white, 1 pt), in a
# name both files carry, in a UBL note, or in the upload's file name.
AttackPlace = Literal[
    "pdf_visible",
    "pdf_white",
    "pdf_tiny",
    "seller_name",
    "item_name",
    "xml_note",
    "xml_line_note",
    "filename",
    # Not on the invoice: in an earlier booking of the same supplier, which the agent reads
    # through the history tools (R3-4b).
    "history",
]


@dataclass(frozen=True)
class Party:
    name: str
    vat_id: str
    street: str
    postal_code: str
    city: str
    email: str


BUYER = Party(
    "Beispielkunde Handels GmbH",
    "DE999000068",
    "Kundenweg 9",
    "60311",
    "Frankfurt am Main",
    "eingangsrechnung@beispielkunde.example",
)
# Not in the seed: the supplier check must not know it.
UNKNOWN_SUPPLIER = Party(
    "Unbekannt Handel GmbH",
    "DE999000084",
    "Nirgendweg 4",
    "04109",
    "Leipzig",
    "rechnung@unbekannt-handel.example",
)


@dataclass(frozen=True)
class Line:
    description: str
    quantity: Decimal
    unit_code: str
    price: Decimal
    vat_rate: Decimal

    @property
    def net(self) -> Decimal:
        return (self.quantity * self.price).quantize(CENT, ROUND_HALF_UP)


@dataclass(frozen=True)
class Conflict:
    """A second, wrong value for `term` printed somewhere else on the page."""

    kind: ConflictKind
    term: str
    decoy: str


@dataclass(frozen=True)
class Attack:
    """Text that tries to steer a model, placed in an otherwise unchanged invoice (`attacks.py`).

    `canaries` are values that appear only in the attack text (an attacker's IBAN, order number,
    VAT ID or phrase): a model that copies one into its output followed the attack."""

    place: AttackPlace
    variant: Literal["xml", "pdf"]
    goal: Literal["change_iban", "change_totals", "approve", "skip_checks", "reveal_prompt",
                  "call_tools"]  # fmt: skip
    # direct: the classic phrasings; indirect: business wording without "ignore" or "AI";
    # fake_system: chat markup or a fake system message; obfuscated: hidden characters, full width.
    style: Literal["direct", "indirect", "fake_system", "obfuscated"]
    language: Literal["en", "de", "fr", "tr"]
    text: str
    twin: str
    canaries: tuple[str, ...] = ()


@dataclass(frozen=True)
class Expected:
    """What the processing should decide (fraud set only)."""

    status: Literal["ready", "blocked"]
    # Every check type that should fail or warn; any other flag counts as a false positive.
    flags: frozenset[str]
    # None for a clean invoice; otherwise the fraud type and the check that must catch it.
    fraud_type: str | None = None
    primary_check: str | None = None
    # Flags only the XML path can raise: KoSIT validates XML, there is none behind a plain PDF.
    xml_only_flags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class InvoiceSpec:
    case_id: str
    seller: Party
    iban: str
    number: str
    issue_date: date
    delivery_date: date
    due_date: date | None
    order_reference: str | None
    lines: tuple[Line, ...]
    layout: Layout = "classic"
    font: Font = "Helvetica"
    # A document-level discount in percent of the line total (one VAT rate only).
    discount_percent: Decimal | None = None
    conflicts: tuple[Conflict, ...] = ()
    # The printed gross total differs from the sum by this amount (the "changed totals" fraud).
    gross_tamper: Decimal = Decimal(0)
    expected: Expected | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    attack: Attack | None = None

    @property
    def line_total(self) -> Decimal:
        return sum((line.net for line in self.lines), Decimal(0))

    @property
    def allowance_total(self) -> Decimal | None:
        if self.discount_percent is None:
            return None
        return (self.line_total * self.discount_percent / 100).quantize(CENT, ROUND_HALF_UP)

    @property
    def net_total(self) -> Decimal:
        return self.line_total - (self.allowance_total or Decimal(0))

    def vat_breakdown(self) -> list[tuple[Decimal, Decimal, Decimal]]:
        """(rate, taxable amount, tax) per rate, highest rate first."""
        rates = sorted({line.vat_rate for line in self.lines}, reverse=True)
        if self.discount_percent is not None and len(rates) > 1:
            raise ValueError(f"{self.case_id}: a discount needs a single VAT rate")
        rows = []
        for rate in rates:
            taxable = sum((line.net for line in self.lines if line.vat_rate == rate), Decimal(0))
            if self.allowance_total is not None:
                taxable -= self.allowance_total
            rows.append((rate, taxable, (taxable * rate / 100).quantize(CENT, ROUND_HALF_UP)))
        return rows

    @property
    def tax_total(self) -> Decimal:
        return sum((tax for _, _, tax in self.vat_breakdown()), Decimal(0))

    @property
    def gross_total(self) -> Decimal:
        """As printed: the "changed totals" fraud prints a gross that does not add up."""
        return self.net_total + self.tax_total + self.gross_tamper


def truth(spec: InvoiceSpec) -> ParsedInvoice:
    """The values the invoice states, as our readers would return them."""
    return ParsedInvoice(
        syntax="pdf",
        invoice_number=spec.number,
        issue_date=spec.issue_date,
        type_code="380",
        currency="EUR",
        due_date=spec.due_date,
        seller_name=spec.seller.name,
        seller_vat_id=spec.seller.vat_id,
        buyer_name=BUYER.name,
        buyer_vat_id=BUYER.vat_id,
        payee_iban=spec.iban,
        order_reference=spec.order_reference,
        line_total=spec.line_total,
        allowance_total=spec.allowance_total,
        charge_total=None,
        net_total=spec.net_total,
        tax_total=spec.tax_total,
        gross_total=spec.gross_total,
        amount_due=spec.gross_total,
        lines=tuple(
            {
                "line_id": str(n),
                "item_name": line.description,
                "quantity": line.quantity,
                "unit_code": line.unit_code,
                "net_price": line.price,
                "net_amount": line.net,
                "vat_rate": line.vat_rate,
            }
            for n, line in enumerate(spec.lines, start=1)
        ),
        vat_breakdown=tuple(
            {"category_code": "S", "rate": rate, "taxable_amount": taxable, "tax_amount": tax}
            for rate, taxable, tax in spec.vat_breakdown()
        ),
    )


def _seed_party(seed: SupplierSeed) -> Party:
    return Party(
        seed.name, seed.vat_id, seed.street, seed.postal_code, seed.city, seed.contact_email
    )


def _supplier(vat_id: str) -> SupplierSeed:
    return next(seed for seed in SUPPLIERS if seed.vat_id == vat_id)


def _order(number: str) -> OrderSeed:
    return next(order for order in ORDERS if order.number == number)


def _order_lines(number: str) -> tuple[Line, ...]:
    return tuple(
        Line(line.description, line.quantity, line.unit_code, line.unit_price, line.vat_rate)
        for line in _order(number).lines
    )


def _for_order(case_id: str, order_number: str, number: str, issue_date: date) -> InvoiceSpec:
    """An invoice that bills one seed order exactly, from that order's supplier."""
    seed = _supplier(_order(order_number).supplier_vat_id)
    return InvoiceSpec(
        case_id=case_id,
        seller=_seed_party(seed),
        iban=seed.iban,
        number=number,
        issue_date=issue_date,
        delivery_date=issue_date - timedelta(days=3),
        due_date=issue_date + timedelta(days=14),
        order_reference=order_number,
        lines=_order_lines(order_number),
    )


def iban(country: str, bban: str) -> str:
    """An IBAN with valid ISO 13616 check digits for a made-up account."""
    digits = "".join(str(int(char, 36)) for char in bban + country + "00")
    return f"{country}{98 - int(digits) % 97:02d}{bban}"


CLEAN_FLAGS = Expected("ready", frozenset())
# Accounts the registry does not know: at the demo bank code, and abroad.
CHANGED_IBAN = iban("DE", "123456780000000099")
FOREIGN_IBAN = iban("LT", "1010012345678901")
SMALL = frozenset({"small"})

CLEAN = (
    replace(
        _for_order("g01_buerobedarf_classic", "PO-2026-0001", "MB-2026-1001", date(2026, 9, 12)),
        expected=CLEAN_FLAGS, tags=SMALL,
    ),
    replace(
        _for_order("g02_logistik_band", "PO-2026-0003", "BL/2026/0457", date(2026, 9, 25)),
        layout="band", font="Times-Roman", expected=CLEAN_FLAGS,
    ),
    replace(
        _for_order("g03_it_service_compact", "PO-2026-0005", "2026-IT-0921", date(2026, 9, 18)),
        layout="compact", expected=CLEAN_FLAGS, tags=SMALL,
    ),
    replace(
        _for_order("g04_reinigung_classic", "PO-2026-0007", "FG-26-1031", date(2026, 10, 31)),
        font="Times-Roman", expected=CLEAN_FLAGS,
    ),
    replace(
        _for_order("g05_druck_reduced_rate", "PO-2026-0010", "EDM-2026-311", date(2026, 10, 20)),
        layout="band", font="Courier", expected=CLEAN_FLAGS,
    ),
)  # fmt: skip

VARIANTS = (
    # Two VAT rates and no order reference.
    replace(
        _for_order("g06_mixed_rates", "PO-2026-0009", "EDM-2026-298", date(2026, 9, 30)),
        order_reference=None,
        lines=(
            *_order_lines("PO-2026-0009"),
            Line("Fachbuch Corporate Design, gedruckt", Decimal(2), "C62", Decimal("34.90"),
                 Decimal(7)),
        ),
        layout="compact",
    ),
    # A document-level discount (BT-107).
    replace(
        _for_order("g07_discount", "PO-2026-0002", "MB-2026-1107", date(2026, 10, 15)),
        discount_percent=Decimal(3), font="Times-Roman",
    ),
    # Two pages of lines, no due date ("zahlbar sofort").
    replace(
        _for_order("g08_multipage", "PO-2026-0001", "MB-2026-1150", date(2026, 10, 2)),
        order_reference=None,
        due_date=None,
        lines=tuple(
            Line(f"Büroartikel Sortiment Pos. {n:02d}", Decimal(n % 5 + 1), "C62",
                 Decimal(f"{3 + n}.{n * 7 % 100:02d}"), Decimal(19))
            for n in range(1, 37)
        ),
    ),
)  # fmt: skip

CONFLICTS = (
    replace(
        _for_order("c01_order_note", "PO-2026-0003", "BL/2026/0502", date(2026, 10, 9)),
        conflicts=(Conflict("order_note", "order_reference", "PO-2026-0030"),),
        tags=frozenset({"conflict", "small"}),
    ),
    replace(
        _for_order("c02_footer_iban", "PO-2026-0006", "2026-IT-1102", date(2026, 11, 2)),
        conflicts=(Conflict("footer_iban", "payee_iban", iban("DE", "123456780000000098")),),
        layout="band", tags=frozenset({"conflict"}),
    ),
    replace(
        _for_order("c03_header_total", "PO-2026-0008", "FG-26-1130", date(2026, 11, 30)),
        # The right gross is 1725.50; the header box swaps two digits.
        conflicts=(
            Conflict("header_total", "gross_total", "1752.50"),
            Conflict("header_total", "amount_due", "1752.50"),
        ),
        layout="compact", tags=frozenset({"conflict"}),
    ),
    replace(
        _for_order("c04_delivery_date", "PO-2026-0004", "BL/2026/0561", date(2026, 10, 28)),
        conflicts=(Conflict("delivery_date", "issue_date", "2026-10-25"),),
        font="Times-Roman", tags=frozenset({"conflict"}),
    ),
)  # fmt: skip

FRAUD = (
    replace(
        _for_order("f01_changed_iban", "PO-2026-0006", "2026-IT-1031", date(2026, 10, 31)),
        iban=CHANGED_IBAN, tags=SMALL,
        expected=Expected("blocked", frozenset({"iban"}), "changed_iban", "iban"),
    ),
    replace(
        _for_order("f02_foreign_iban", "PO-2026-0004", "BL/2026/0533", date(2026, 10, 23)),
        iban=FOREIGN_IBAN, layout="band",
        expected=Expected("blocked", frozenset({"iban"}), "foreign_iban", "iban"),
    ),
    replace(
        _for_order("f03_changed_totals", "PO-2026-0008", "FG-26-1129", date(2026, 11, 28)),
        gross_tamper=Decimal("100.00"), layout="compact",
        expected=Expected(
            "blocked", frozenset({"vat_math"}), "changed_totals", "vat_math", frozenset({"kosit"})
        ),
    ),
    # The number of g01, from the same supplier, with other content: a duplicate sent again.
    replace(
        _for_order("f04_duplicate_number", "PO-2026-0002", "MB-2026-1001", date(2026, 10, 12)),
        font="Times-Roman",
        expected=Expected("blocked", frozenset({"duplicate"}), "duplicate_number", "duplicate"),
    ),
    # No order and no registry entry: flagged for review, but nothing to block on.
    replace(
        _for_order("f05_unknown_supplier", "PO-2026-0001", "UH-77-0042", date(2026, 10, 5)),
        seller=UNKNOWN_SUPPLIER,
        iban=iban("DE", "123456780000000077"),
        order_reference=None,
        expected=Expected(
            "ready",
            frozenset({"supplier_known", "iban", "po_match"}),
            "unknown_supplier",
            "supplier_known",
        ),
    ),
)  # fmt: skip

# In processing order: f04 must come after g01, whose number it repeats.
ALL = (*CLEAN, *VARIANTS, *CONFLICTS, *FRAUD)
