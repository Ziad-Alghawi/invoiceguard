"""What the checks read (`CheckContext`) and what they return (`CheckResult`).

The context is loaded once from the database and the validator (`context.py`); every check is
then a pure function of it, so checks are unit-tested without a database or network.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from invoiceguard_api.extraction.model import FieldConfidence
from invoiceguard_api.models import CheckStatus
from invoiceguard_api.parsing import ParsedInvoice

# Amounts on an invoice are rounded to cents, so two sums may differ by one cent.
TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class CheckResult:
    type: str
    status: CheckStatus
    # One sentence for the reviewer; the details are in `evidence`.
    message: str
    # JSON-ready: amounts and dates as strings.
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VerifiedIban:
    iban: str
    since: date
    verified_by: str | None


@dataclass(frozen=True)
class KnownSupplier:
    id: uuid.UUID
    name: str
    vat_id: str
    verified_ibans: tuple[VerifiedIban, ...]


@dataclass(frozen=True)
class OrderLine:
    line_no: int
    description: str
    quantity: Decimal
    unit_code: str
    unit_price: Decimal


@dataclass(frozen=True)
class Order:
    id: uuid.UUID
    number: str
    supplier_id: uuid.UUID
    currency: str
    lines: tuple[OrderLine, ...]


@dataclass(frozen=True)
class OtherInvoice:
    """Another stored invoice from the same seller, as a duplicate candidate."""

    id: uuid.UUID
    invoice_number: str
    issue_date: date
    gross_total: Decimal
    status: str


@dataclass(frozen=True)
class ValidationMessage:
    level: str
    code: str
    text: str


@dataclass(frozen=True)
class Validation:
    """What the KoSIT validator said about the invoice XML (ADR-009)."""

    # "not_applicable": there is no XML to validate (fields extracted from a PDF by an LLM).
    outcome: Literal["accepted", "rejected", "no_scenario", "unavailable", "not_applicable"]
    scenario: str | None = None
    messages: tuple[ValidationMessage, ...] = ()
    # Why there is no result, when `outcome` is "unavailable" or "not_applicable".
    reason: str | None = None


@dataclass(frozen=True)
class CheckContext:
    invoice: ParsedInvoice
    validation: Validation
    supplier: KnownSupplier | None
    order: Order | None
    other_invoices: tuple[OtherInvoice, ...]
    # LLM extraction only (ADR-010); empty for invoices read from XML.
    confidences: tuple[FieldConfidence, ...] = ()
    confidence_threshold: Decimal = Decimal(1)
