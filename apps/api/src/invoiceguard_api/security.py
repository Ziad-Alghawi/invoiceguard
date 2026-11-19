"""Security events (R2-4): what is written to the append-only `security_events` log.

Writers add an event to their session and commit it with the rest of their work; an event for a
refused request is committed before the error is raised, so the refusal itself is on record.
The list for approvers is in security_events.py.
"""

import uuid
from typing import Any

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from invoiceguard_api.models import SecurityEvent, SecuritySeverity, User, UserRole

LOGIN_FAILED = "login_failed"
ACCOUNT_LOCKED = "account_locked"
LOGIN_RATE_LIMITED = "login_rate_limited"
FORBIDDEN = "forbidden"
SELF_APPROVAL = "self_approval_attempt"
INJECTION = "injection_suspected"


def security_event(
    event_type: str,
    severity: SecuritySeverity,
    *,
    invoice_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    **details: Any,
) -> SecurityEvent:
    return SecurityEvent(
        type=event_type,
        severity=severity,
        invoice_id=invoice_id,
        user_id=user_id,
        details=details,
    )


def refuse(session: Session, event: SecurityEvent, message: str) -> HTTPException:
    """Commit the event for a refused request and return the 403 to raise."""
    session.add(event)
    session.commit()
    return HTTPException(status.HTTP_403_FORBIDDEN, message)


def forbidden_event(request: Request, user: User, required: UserRole) -> SecurityEvent:
    """A refused role check: who, which request, which role it needed."""
    return security_event(
        FORBIDDEN,
        SecuritySeverity.MEDIUM,
        user_id=user.id,
        method=request.method,
        path=request.url.path,
        role=user.role.value,
        required_role=required.value,
    )
