"""Human review (ADR-003, ADR-012, ADR-015, ADR-016): approve, reject and the four-eyes
override of a blocked invoice, and the audit history.

A logged-in user decides; nothing else sets a decision's status. A `ready` invoice is approved
by one person. A `blocked` invoice (at least one failed check) needs two: a reviewer requests an
override with a reason (`override_requested`), and a different user with the approver role
confirms it (`approved`) or declines it (back to `blocked`), each with a reason. The endpoints
check these rules under the invoice's advisory lock, then resume the invoice's paused graph
thread with the decision; the graph's decide node checks the four-eyes rule again and writes
the status and the audit row in one transaction. The lock makes two users clicking at the same
time decide one after the other, so the second one gets a 409.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from invoiceguard_api.auth import CurrentUser, current_user
from invoiceguard_api.checkpoints import lock_invoice
from invoiceguard_api.db import DbSession
from invoiceguard_api.invoices import ErrorOut, InvoiceOut, get_invoice_or_404
from invoiceguard_api.models import AuditEvent, Invoice, InvoiceStatus, User, UserRole
from invoiceguard_api.processing import (
    IN_REVIEW,
    Action,
    Decision,
    Services,
    apply_decision,
    failed_checks,
    override_requester,
)

router = APIRouter(prefix="/invoices", tags=["review"], dependencies=[Depends(current_user)])

# Leading and trailing spaces are removed; a reason of only spaces is empty and refused.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

# Every status a thread waits at review in (ready, blocked, failed, awaiting_extraction,
# override_requested); not while processing: the run would overwrite the decision with its result.
REJECTABLE = IN_REVIEW

DECISION_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Unknown invoice"},
    status.HTTP_409_CONFLICT: {
        "model": ErrorOut,
        "description": "Not in a status that allows this decision",
    },
}
OVERRIDE_DECISION_RESPONSES: dict[int | str, dict[str, Any]] = {
    **DECISION_RESPONSES,
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorOut,
        "description": "Not an approver, or the user who requested the override",
    },
}


class ApproveIn(BaseModel):
    # Nothing to send. A blocked invoice is approved through the override endpoints, so an
    # `override_reason` from an older client is refused (422) instead of ignored.
    model_config = ConfigDict(extra="forbid")


class ReasonIn(BaseModel):
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


def _forbidden(message: str) -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, message)


def _require_status(invoice: Invoice, expected: InvoiceStatus, action: str) -> None:
    if invoice.status is not expected:
        raise _conflict(
            f"The invoice is {invoice.status.value}; only {expected.value} invoices can {action}."
        )


def _decision(user: User, invoice: Invoice, action: Action, reason: str | None) -> Decision:
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
    """Approve a `ready` invoice. A blocked invoice needs a four-eyes override instead."""
    invoice = _lock(session, invoice_id)
    if invoice.status is InvoiceStatus.BLOCKED:
        failed = ", ".join(failed_checks(session, invoice.id))
        raise _conflict(
            f"The invoice is blocked by failed checks ({failed}); request an override with a "
            "reason, which a second person with the approver role confirms."
        )
    if invoice.status is InvoiceStatus.OVERRIDE_REQUESTED:
        raise _conflict(
            "An override is requested for this invoice; an approver confirms or declines it."
        )
    _require_status(invoice, InvoiceStatus.READY, "be approved")
    return _resume(session, request, invoice, _decision(user, invoice, "approve", None))


@router.post("/{invoice_id}/reject", responses=DECISION_RESPONSES)
def reject_invoice(
    invoice_id: uuid.UUID,
    body: ReasonIn,
    session: DbSession,
    user: CurrentUser,
    request: Request,
) -> InvoiceOut:
    """Reject an invoice with a reason; it is then out of the review queue."""
    invoice = _lock(session, invoice_id)
    if invoice.status not in REJECTABLE:
        raise _conflict(
            f"The invoice is {invoice.status.value}; only ready, blocked, failed, "
            "awaiting_extraction or override_requested invoices can be rejected."
        )
    return _resume(session, request, invoice, _decision(user, invoice, "reject", body.reason))


@router.post("/{invoice_id}/override", responses=DECISION_RESPONSES)
def request_override(
    invoice_id: uuid.UUID,
    body: ReasonIn,
    session: DbSession,
    user: CurrentUser,
    request: Request,
) -> InvoiceOut:
    """Ask to approve a `blocked` invoice despite its failed checks, with a written reason.

    The invoice waits in `override_requested` until another user with the approver role
    confirms or declines the request.
    """
    invoice = _lock(session, invoice_id)
    _require_status(invoice, InvoiceStatus.BLOCKED, "get an override")
    decision = _decision(user, invoice, "request_override", body.reason)
    return _resume(session, request, invoice, decision)


def _decide_override(
    session: Session,
    request: Request,
    user: User,
    invoice_id: uuid.UUID,
    action: Action,
    reason: str,
) -> InvoiceOut:
    """Confirm or decline a requested override: an approver, never the requester."""
    if user.role is not UserRole.APPROVER:
        raise _forbidden("Only a user with the approver role can decide an override.")
    invoice = _lock(session, invoice_id)
    _require_status(invoice, InvoiceStatus.OVERRIDE_REQUESTED, "have an override decided")
    if override_requester(session, invoice.id) == user.id:
        raise _forbidden(
            "You requested this override; a different approver has to decide it (four eyes)."
        )
    return _resume(session, request, invoice, _decision(user, invoice, action, reason))


@router.post("/{invoice_id}/override/confirm", responses=OVERRIDE_DECISION_RESPONSES)
def confirm_override(
    invoice_id: uuid.UUID,
    body: ReasonIn,
    session: DbSession,
    user: CurrentUser,
    request: Request,
) -> InvoiceOut:
    """Approver only: confirm another user's override request; the invoice is `approved`."""
    return _decide_override(session, request, user, invoice_id, "confirm_override", body.reason)


@router.post("/{invoice_id}/override/decline", responses=OVERRIDE_DECISION_RESPONSES)
def decline_override(
    invoice_id: uuid.UUID,
    body: ReasonIn,
    session: DbSession,
    user: CurrentUser,
    request: Request,
) -> InvoiceOut:
    """Approver only: decline an override request; the invoice is `blocked` again."""
    return _decide_override(session, request, user, invoice_id, "decline_override", body.reason)


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
