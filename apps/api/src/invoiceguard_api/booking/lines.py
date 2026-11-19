"""An invoice's lines as booking sees them: the line number and the normalised item name."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from invoiceguard_api.booking.text import normalise
from invoiceguard_api.models import InvoiceField
from invoiceguard_api.parsing.fields import LINE_TERMS

ITEM_NAME = LINE_TERMS["item_name"]


@dataclass(frozen=True)
class InvoiceLine:
    line_no: int
    # Normalised item name (BT-153).
    text: str


def invoice_lines(session: Session, invoice_id: uuid.UUID) -> list[InvoiceLine]:
    """The invoice's lines with an item name, in order."""
    rows = session.execute(
        select(InvoiceField.line_no, InvoiceField.value)
        .where(
            InvoiceField.invoice_id == invoice_id,
            InvoiceField.code == ITEM_NAME,
            InvoiceField.line_no.is_not(None),
        )
        .order_by(InvoiceField.line_no)
    ).all()
    return [
        InvoiceLine(line_no, normalise(value)) for line_no, value in rows if line_no is not None
    ]
