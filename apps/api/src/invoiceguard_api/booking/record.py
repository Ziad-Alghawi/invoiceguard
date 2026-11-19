"""Storing the accounts a person chose when approving an invoice (ADR-020).

Called by the graph's decide node in the decision's transaction, so the bookings and the
`approved` status are written together or not at all. From then on the lines are history that
suggestions for later invoices are retrieved from, unless the invoice failed the prompt-injection
check: its bookings are kept as the record of the decision but never retrieved (poisoning of the
index, PLAN section 5, ASI06).
"""

import uuid
from datetime import date
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from invoiceguard_api.booking.lines import invoice_lines
from invoiceguard_api.booking.text import text_sha256
from invoiceguard_api.checks.injection import CHECK_TYPE as INJECTION_CHECK
from invoiceguard_api.checks.supplier import normalise_vat_id
from invoiceguard_api.models import Booking, BookingSource, Check, CheckStatus, InvoiceField
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS


class BookingChoice(TypedDict):
    """One line's account as the person chose it; plain JSON, it travels in the graph state."""

    line_no: int
    account: str
    # The top suggestion when the person decided; None when there was none.
    suggested_account: str | None


def _document_terms(session: Session, invoice_id: uuid.UUID) -> dict[str, str]:
    codes = {DOCUMENT_TERMS[name]: name for name in DOCUMENT_TERMS}
    rows = session.execute(
        select(InvoiceField.code, InvoiceField.value).where(
            InvoiceField.invoice_id == invoice_id,
            InvoiceField.line_no.is_(None),
            InvoiceField.code.in_(list(codes)),
        )
    ).all()
    return {codes[code]: value for code, value in rows}


def injection_flagged(session: Session, invoice_id: uuid.UUID) -> bool:
    return bool(
        session.scalar(
            select(func.count(Check.id)).where(
                Check.invoice_id == invoice_id,
                Check.type == INJECTION_CHECK,
                Check.status == CheckStatus.FAILED,
            )
        )
    )


def record_bookings(
    session: Session,
    invoice_id: uuid.UUID,
    user_id: uuid.UUID,
    choices: list[BookingChoice],
) -> None:
    """Add one booking per chosen line; the caller commits. A line number the invoice does not
    have raises KeyError (the endpoints check this first)."""
    texts = {line.line_no: line.text for line in invoice_lines(session, invoice_id)}
    terms = _document_terms(session, invoice_id)
    vat_id = terms.get("seller_vat_id")
    issue_date = terms.get("issue_date")
    searchable = not injection_flagged(session, invoice_id)
    for choice in choices:
        text = texts[choice["line_no"]]
        session.add(
            Booking(
                source=BookingSource.INVOICE,
                invoice_id=invoice_id,
                line_no=choice["line_no"],
                supplier_vat_id=None if vat_id is None else normalise_vat_id(vat_id),
                supplier_name=terms.get("seller_name"),
                invoice_number=terms.get("invoice_number"),
                issue_date=None if issue_date is None else date.fromisoformat(issue_date),
                text=text,
                text_sha256=text_sha256(text),
                account=choice["account"],
                suggested_account=choice["suggested_account"],
                searchable=searchable,
                user_id=user_id,
            )
        )
