"""Human review (ADR-003, ADR-012, ADR-015): approve or reject an invoice, and read its audit
history.

A logged-in reviewer decides; nothing else sets `approved` or `rejected`. A `blocked` invoice
(at least one failed check) is approved only with a written override reason. The endpoints
check these rules under the invoice's advisory lock, then resume the invoice's paused graph
thread with the decision; the graph's decide node writes the status and the audit rows in one
transaction. The lock makes two reviewers clicking at the same time decide one after the other,
so the second one gets a 409.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from invoiceguard_api.auth import CurrentUser, current_user
from invoiceguard_api.checkpoints import lock_invoice
from invoiceguard_api.db import DbSession
from invoiceguard_api.invoices import ErrorOut, InvoiceOut, get_invoice_or_404
from invoiceguard_api.models import AuditEvent, Invoice, InvoiceStatus, User
from invoiceguard_api.processing import IN_REVIEW, Decision, Services, apply_decision, failed_checks

router = APIRouter(prefix="/invoices", tags=["review"], dependencies=[Depends(current_user)])

# Leading and trailing spaces are removed; a reason of only spaces is empty and refused.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

APPROVABLE = frozenset({InvoiceStatus.READY, InvoiceStatus.BLOCKED})
# Every status a thread waits at review in (ready, blocked, failed, awaiting_extraction); not
# while processing: the run would overwrite the decision with its result.
REJECTABLE = IN_REVIEW

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
    """The invoice under its advisory lock, held until the request's transaction ends."""
    lock_invoice(session, invoice_id)
    invoice = session.get(Invoice, invoice_id, populate_existing=True)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")
    return invoice


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, message)


def _decision(
    user: User, invoice: Invoice, action: Literal["approve", "reject"], reason: str | None
) -> Decision:
    return {
        "action": action,
        "user_id": str(user.id),
        "actor": user.email,
        "status_before": invoice.status.value,
        "reason": reason,
    }


def _resume(session: Session, request: Request, invoice: Invoice, decision: Decision) -> InvoiceOut:
    state = request.app.state
    services = Services(state.session_factory, state.storage, state.validator, state.extractor)
    apply_decision(services, invoice.id, decision)
    # The graph committed on its own connection; read the result, then release the lock.
    session.refresh(invoice)
    session.commit()
    return InvoiceOut.model_validate(invoice)


@router.post("/{invoice_id}/approve", responses=DECISION_RESPONSES)
def approve_invoice(
    invoice_id: uuid.UUID,
    body: ApproveIn,
    session: DbSession,
    user: CurrentUser,
    request: Request,
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
    if invoice.status is InvoiceStatus.BLOCKED and override is None:
        failed = ", ".join(failed_checks(session, invoice.id))
        raise _conflict(
            f"The invoice is blocked by failed checks ({failed}); approving it needs an override "
            "reason."
        )
    return _resume(session, request, invoice, _decision(user, invoice, "approve", override))


@router.post("/{invoice_id}/reject", responses=DECISION_RESPONSES)
def reject_invoice(
    invoice_id: uuid.UUID,
    body: RejectIn,
    session: DbSession,
    user: CurrentUser,
    request: Request,
) -> InvoiceOut:
    """Reject an invoice with a reason; it is then out of the review queue."""
    invoice = _lock(session, invoice_id)
    if invoice.status not in REJECTABLE:
        raise _conflict(
            f"The invoice is {invoice.status.value}; only ready, blocked, failed or "
            "awaiting_extraction invoices can be rejected."
        )
    return _resume(session, request, invoice, _decision(user, invoice, "reject", body.reason))


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
