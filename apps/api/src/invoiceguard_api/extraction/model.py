"""What an extraction run returns: the invoice, a confidence per field, and every model call."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from invoiceguard_api.models import ModelCallStatus
from invoiceguard_api.parsing import ParsedInvoice


@dataclass(frozen=True)
class FieldConfidence:
    """How sure the model is about one field, a whole invoice line, or a VAT breakdown row."""

    # What a reviewer reads: "payee_iban", "line 2", "vat_breakdown 1".
    name: str
    # The BT code of a document-level term; None for lines and VAT rows.
    code: str | None
    # The 1-based line number of an invoice line; None otherwise.
    line_no: int | None
    confidence: Decimal
    # {"page": 1, "snippet": "..."}; None when the model found no value.
    evidence: dict[str, Any] | None


@dataclass(frozen=True)
class Extraction:
    invoice: ParsedInvoice
    confidences: tuple[FieldConfidence, ...]


@dataclass(frozen=True)
class CallRecord:
    """One model call, as it goes into `model_calls`."""

    # When the call started.
    at: datetime
    model: str
    status: ModelCallStatus
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    latency_ms: int
    error: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    calls: tuple[CallRecord, ...]
    # Exactly one of the two is set.
    extraction: Extraction | None
    failure: str | None = None
