"""Human review (ADR-003, ADR-012): approve or reject an invoice, and read its audit history.

A logged-in reviewer decides; nothing else sets `approved` or `rejected`. A `blocked` invoice
(at least one failed check) is approved only with a written override reason. Each decision and
its audit rows are written in one transaction, on the invoice row locked with FOR UPDATE, so two
reviewers clicking at the same time cannot both decide.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from invoiceguard_api.auth import CurrentUser, current_user
from invoiceguard_api.db import DbSession
from invoiceguard_api.invoices import ErrorOut, InvoiceOut, get_invoice_or_404
from invoiceguard_api.models import (
    AuditEvent,
    Check,
    CheckStatus,
    Invoice,
    InvoiceStatus,
    User,
)

router = APIRouter(prefix="/invoices", tags=["review"], dependencies=[Depends(current_user)])

# Leading and trailing spaces are removed; a reason of only spaces is empty and refused.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

APPROVABLE = frozenset({InvoiceStatus.READY, InvoiceStatus.BLOCKED})
# Not while processing: the background task would overwrite the decision with its result.
REJECTABLE = frozenset(
    {
        InvoiceStatus.READY,
        InvoiceStatus.BLOCKED,
        InvoiceStatus.FAILED,
        InvoiceStatus.AWAITING_EXTRACTION,
    }
)

DECISION_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Unknown invoice"},
    status.HTTP_409_CONFLICT: {
        "model": ErrorOut,
        "description": "Not in a status that allows this decision, or blocked without override",
    },
}


class ApproveIn(BaseModel):
    # Required to approve a `blocked` invoice; refused for a `ready` one (nothing to override).
    override_reason: Reason | None = None


class RejectIn(BaseModel):
    reason: Reason


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    at: datetime
    actor: str
    action: str
    status_before: str | None
    status_after: str | None
    reason: str | None
    details: dict[str, Any]


def _lock(session: Session, invoice_id: uuid.UUID) -> Invoice:
    invoice = session.get(Invoice, invoice_id, with_for_update=True, populate_existing=True)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")
    return invoice


def _event(
    user: User,
    action: str,
    invoice: Invoice,
    new_status: InvoiceStatus,
    reason: str | None,
    **details: Any,
) -> AuditEvent:
    return AuditEvent(
        actor=user.email,
        user_id=user.id,
        action=action,
        entity_type="invoice",
        entity_id=str(invoice.id),
        status_before=invoice.status.value,
        status_after=new_status.value,
        reason=reason,
        details=details,
    )


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _failed_checks(session: Session, invoice_id: uuid.UUID) -> list[str]:
    return list(
        session.scalars(
            select(Check.type)
            .where(Check.invoice_id == invoice_id, Check.status == CheckStatus.FAILED)
            .order_by(Check.type)
        )
    )


def _decide(
    session: Session, invoice: Invoice, new_status: InvoiceStatus, reason: str | None
) -> InvoiceOut:
    invoice.status = new_status
    invoice.status_reason = reason
    session.commit()
    session.refresh(invoice)
    return InvoiceOut.model_validate(invoice)


@router.post("/{invoice_id}/approve", responses=DECISION_RESPONSES)
def approve_invoice(
    invoice_id: uuid.UUID, body: ApproveIn, session: DbSession, user: CurrentUser
) -> InvoiceOut:
    """Approve a `ready` invoice, or a `blocked` one with `override_reason`."""
    invoice = _lock(session, invoice_id)
    if invoice.status not in APPROVABLE:
        raise _conflict(
            f"The invoice is {invoice.status.value}; only ready or blocked invoices can be "
            "approved."
        )
    override = body.override_reason
    if invoice.status is InvoiceStatus.READY and override is not None:
        raise _conflict("The invoice has no failed checks to override; approve it without one.")
    if invoice.status is InvoiceStatus.BLOCKED:
        failed = _failed_checks(session, invoice.id)
        if override is None:
            raise _conflict(
                f"The invoice is blocked by failed checks ({', '.join(failed)}); approving it "
                "needs an override reason."
            )
        # The override first, then the approval it allowed; the identity id keeps this order.
        session.add(
            _event(
                user,
                "invoice.override",
                invoice,
                InvoiceStatus.APPROVED,
                override,
                failed_checks=failed,
            )
        )
    session.add(_event(user, "invoice.approved", invoice, InvoiceStatus.APPROVED, override))
    return _decide(session, invoice, InvoiceStatus.APPROVED, override)


@router.post("/{invoice_id}/reject", responses=DECISION_RESPONSES)
def reject_invoice(
    invoice_id: uuid.UUID, body: RejectIn, session: DbSession, user: CurrentUser
) -> InvoiceOut:
    """Reject an invoice with a reason; it is then out of the review queue."""
    invoice = _lock(session, invoice_id)
    if invoice.status not in REJECTABLE:
        raise _conflict(
            f"The invoice is {invoice.status.value}; only ready, blocked, failed or "
            "awaiting_extraction invoices can be rejected."
        )
    session.add(_event(user, "invoice.rejected", invoice, InvoiceStatus.REJECTED, body.reason))
    return _decide(session, invoice, InvoiceStatus.REJECTED, body.reason)


@router.get(
    "/{invoice_id}/audit",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Unknown invoice"}},
)
def invoice_audit(invoice_id: uuid.UUID, session: DbSession) -> list[AuditEventOut]:
    """Everything that happened to the invoice, oldest first (read-only)."""
    get_invoice_or_404(session, invoice_id)
    events = session.scalars(
        select(AuditEvent)
        .where(AuditEvent.entity_type == "invoice", AuditEvent.entity_id == str(invoice_id))
        .order_by(AuditEvent.id)
    )
    return [AuditEventOut.model_validate(event) for event in events]
