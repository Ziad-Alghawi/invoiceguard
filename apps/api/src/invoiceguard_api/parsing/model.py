"""The typed result of reading an e-invoice, and the errors the readers raise."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

Syntax = Literal["cii", "ubl"]


class ParseError(Exception):
    """The file cannot be read into an invoice; the message is shown to the user as the reason."""


class UnsupportedFormat(ParseError):
    """Well-formed XML, but not a syntax we read (ZUGFeRD 1.0, UBL credit note, anything else)."""


class InvalidInvoice(ParseError):
    """Broken, unsafe or incomplete XML, or a PDF that cannot be opened."""


class NoEmbeddedXml(Exception):
    """A PDF without an e-invoice attachment; it needs LLM extraction instead (R1-5)."""


class ParsedLine(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    line_id: str
    item_name: str
    quantity: Decimal
    unit_code: str
    net_price: Decimal
    net_amount: Decimal
    vat_rate: Decimal | None


class VatBreakdown(BaseModel):
    """One VAT breakdown group (BG-23): the taxable amount and tax for one category and rate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category_code: str
    # None for categories without a rate in the file (for example "O", not subject to VAT).
    rate: Decimal | None
    taxable_amount: Decimal
    tax_amount: Decimal


class ParsedInvoice(BaseModel):
    """The EN 16931 business terms R1 needs; `fields.py` maps each one to its BT code."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    syntax: Syntax
    invoice_number: str
    issue_date: date
    type_code: str
    currency: str
    due_date: date | None
    seller_name: str
    seller_vat_id: str | None
    buyer_name: str
    buyer_vat_id: str | None
    # None is a valid case (direct debit, card payment), not an error: see ADR-005.
    payee_iban: str | None
    order_reference: str | None
    # BT-106, BT-107, BT-108: sum of line net amounts, document allowances and charges.
    line_total: Decimal | None
    allowance_total: Decimal | None
    charge_total: Decimal | None
    net_total: Decimal
    tax_total: Decimal | None
    gross_total: Decimal
    amount_due: Decimal
    lines: tuple[ParsedLine, ...]
    vat_breakdown: tuple[VatBreakdown, ...]
    # Things a later check should look at, for example several payee IBANs.
    warnings: tuple[str, ...] = ()
