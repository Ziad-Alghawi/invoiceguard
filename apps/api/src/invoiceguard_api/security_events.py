"""The security events list for approvers (R2-4): read-only, newest first."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select

from invoiceguard_api.auth import CurrentUser, ErrorOut
from invoiceguard_api.db import DbSession
from invoiceguard_api.models import SecurityEvent, SecuritySeverity, User, UserRole
from invoiceguard_api.security import forbidden_event, refuse

router = APIRouter(prefix="/security-events", tags=["security"])


def require_approver(request: Request, session: DbSession, user: CurrentUser) -> User:
    """The logged-in user if they are an approver; otherwise 403 and a security event."""
    if user.role is not UserRole.APPROVER:
        raise refuse(
            session,
            forbidden_event(request, user, UserRole.APPROVER),
            "Only a user with the approver role can read the security events.",
        )
    return user


class SecurityEventOut(BaseModel):
    id: int
    at: datetime
    type: str
    severity: SecuritySeverity
    invoice_id: uuid.UUID | None
    user_id: uuid.UUID | None
    # The email of `user_id`, so the list reads without a second lookup.
    user_email: str | None
    details: dict[str, Any]


@router.get(
    "",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorOut, "description": "Not logged in"},
        status.HTTP_403_FORBIDDEN: {"model": ErrorOut, "description": "Not an approver"},
    },
)
def list_security_events(
    session: DbSession,
    response: Response,
    _: Annotated[User, Depends(require_approver)],
    event_type: Annotated[list[str] | None, Query(alias="type", max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SecurityEventOut]:
    """Security events, newest first (approvers only). Repeat `type` to filter, for example
    `?type=login_failed&type=account_locked`; `X-Total-Count` holds the number of matches."""
    query = select(SecurityEvent, User.email).outerjoin(User, User.id == SecurityEvent.user_id)
    count = select(func.count(SecurityEvent.id))
    if event_type:
        query = query.where(SecurityEvent.type.in_(event_type))
        count = count.where(SecurityEvent.type.in_(event_type))
    response.headers["X-Total-Count"] = str(session.scalar(count))
    rows = session.execute(query.order_by(SecurityEvent.id.desc()).limit(limit).offset(offset))
    return [
        SecurityEventOut(
            id=event.id,
            at=event.at,
            type=event.type,
            severity=event.severity,
            invoice_id=event.invoice_id,
            user_id=event.user_id,
            user_email=email,
            details=event.details,
        )
        for event, email in rows
    ]
