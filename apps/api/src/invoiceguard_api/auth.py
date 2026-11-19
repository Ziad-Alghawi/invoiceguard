"""Login with seeded users and server-side sessions in an HttpOnly cookie (ADR-006, ADR-011).

The cookie holds a random token; the database stores only its SHA-256, so a leaked database does
not contain usable sessions, and logout ends the session on the server. Failed logins in a row
lock the account for a while. Every login, logout and failed login is written to the audit log.

On top of that, one client address may fail only so often within a window, whatever accounts it
tries (R4-2): then it gets 429 before any account is looked up or any password hashed. The
address comes from X-Forwarded-For only when a trusted proxy sent it (settings.trusted_proxies),
and it is kept in `login_failures` for the window only.
"""

import hashlib
import math
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Annotated, Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from invoiceguard_api.db import DbSession
from invoiceguard_api.models import (
    AuditEvent,
    LoginFailure,
    SecurityEvent,
    SecuritySeverity,
    User,
    UserRole,
    UserSession,
)
from invoiceguard_api.security import ACCOUNT_LOCKED, LOGIN_RATE_LIMITED, security_event
from invoiceguard_api.security import LOGIN_FAILED as LOGIN_FAILED_EVENT
from invoiceguard_api.settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"])

SESSION_COOKIE = "invoiceguard_session"
TOKEN_BYTES = 32
ANONYMOUS_ACTOR = "anonymous"
SYSTEM_ACTOR = "system"
# One message for an unknown email and a wrong password, so the reply does not reveal which.
LOGIN_FAILED = "Wrong email or password."
NOT_LOGGED_IN = "Not logged in."
IP_LIMITED = "Too many failed logins from your network; try again in a few minutes."

# Argon2id with the library defaults (RFC 9106 low-memory profile).
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


@cache
def _dummy_hash() -> str:
    return _hasher.hash(secrets.token_urlsafe(16))


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalise_email(email: str) -> str:
    return email.strip().lower()


class LoginIn(BaseModel):
    email: str = Field(min_length=1, max_length=255)
    password: SecretStr = Field(min_length=1, max_length=1024)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: UserRole


class ErrorOut(BaseModel):
    detail: str


def _event(
    action: str,
    entity_id: str,
    *,
    user: User | None = None,
    actor: str = ANONYMOUS_ACTOR,
    reason: str | None = None,
    **details: Any,
) -> AuditEvent:
    return AuditEvent(
        actor=user.email if user is not None else actor,
        user_id=None if user is None else user.id,
        action=action,
        entity_type="user",
        entity_id=entity_id,
        reason=reason,
        details=details,
    )


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _login_failed(reason: str, user: User | None = None, **details: Any) -> SecurityEvent:
    """A failed login for the security log (R2-4), next to its audit event."""
    return security_event(
        LOGIN_FAILED_EVENT,
        SecuritySeverity.LOW,
        user_id=None if user is None else user.id,
        reason=reason,
        **details,
    )


def _client_ip(request: Request) -> str | None:
    """The client's address: from X-Forwarded-For when a trusted proxy sent it (the proxy
    headers middleware has already applied it, main.py), else the connecting address."""
    return request.client.host if request.client is not None else None


def _ip_retry_after(
    session: Session, client_ip: str | None, now: datetime, settings: Settings
) -> int | None:
    """Seconds until the address may try again, or None if it may now. Deletes the failures
    that have left the window, for every address."""
    limit = settings.login_ip_max_failures
    window = timedelta(minutes=settings.login_ip_window_minutes)
    session.execute(delete(LoginFailure).where(LoginFailure.at <= now - window))
    if limit is None or client_ip is None:
        return None
    recent = session.scalars(
        select(LoginFailure.at)
        .where(LoginFailure.client_ip == client_ip, LoginFailure.at > now - window)
        .order_by(LoginFailure.at.desc())
        .limit(limit)
    ).all()
    if len(recent) < limit:
        return None
    # Below the limit again once the limit-th newest failure leaves the window.
    return max(1, math.ceil((recent[-1] + window - now).total_seconds()))


def _count_failure(session: Session, client_ip: str | None, now: datetime) -> None:
    if client_ip is not None:
        session.add(LoginFailure(client_ip=client_ip, at=now))


def _failed(session: Session, user: User, now: datetime, settings: Settings) -> None:
    """Count a wrong password; the last allowed one starts a lockout."""
    user.failed_logins += 1
    session.add(_event("auth.login_failed", str(user.id), reason="wrong_password"))
    session.add(_login_failed("wrong_password", user, failed_logins=user.failed_logins))
    if user.failed_logins >= settings.login_max_failures:
        user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
        reason = f"{user.failed_logins} failed logins in a row"
        session.add(
            _event(
                "auth.locked",
                str(user.id),
                actor=SYSTEM_ACTOR,
                reason=reason,
                locked_until=user.locked_until.isoformat(),
            )
        )
        session.add(
            security_event(
                ACCOUNT_LOCKED,
                SecuritySeverity.MEDIUM,
                user_id=user.id,
                reason=reason,
                locked_until=user.locked_until.isoformat(),
            )
        )
        user.failed_logins = 0
    session.commit()


@router.post(
    "/login",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ErrorOut, "description": "Wrong credentials"},
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": ErrorOut,
            "description": "Account locked, or too many failed logins from this address",
        },
    },
)
def login(body: LoginIn, session: DbSession, request: Request, response: Response) -> UserOut:
    """Check email and password and start a session (cookie `invoiceguard_session`)."""
    settings = _settings(request)
    email = normalise_email(body.email)
    password = body.password.get_secret_value()
    now = datetime.now(UTC)
    client_ip = _client_ip(request)
    # Before the account and the password: a refused address costs no hashing. Counted without
    # a lock, so parallel attempts can pass the limit by a few.
    if (retry_after := _ip_retry_after(session, client_ip, now, settings)) is not None:
        # The security log never stores the address (personal data).
        session.add(security_event(LOGIN_RATE_LIMITED, SecuritySeverity.MEDIUM, email=email))
        session.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, IP_LIMITED, headers={"Retry-After": str(retry_after)}
        )
    # Locked, so parallel attempts cannot each read the same failure count.
    user = session.scalar(select(User).where(User.email == email).with_for_update())

    if user is None:
        # Same work as a wrong password, so timing does not reveal which emails exist.
        _verify(_dummy_hash(), password)
        session.add(_event("auth.login_failed", "unknown", reason="unknown_email", email=email))
        session.add(_login_failed("unknown_email", email=email))
        _count_failure(session, client_ip, now)
        session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED)

    if user.locked_until is not None and user.locked_until > now:
        # The password is not checked while locked, so guessing gains nothing.
        session.add(_event("auth.login_failed", str(user.id), reason="locked"))
        session.add(_login_failed("locked", user))
        _count_failure(session, client_ip, now)
        session.commit()
        retry_after = max(1, int((user.locked_until - now).total_seconds()))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many failed logins; this account is locked for a few minutes.",
            headers={"Retry-After": str(retry_after)},
        )

    if not _verify(user.password_hash, password):
        _count_failure(session, client_ip, now)
        _failed(session, user, now, settings)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED)

    user.failed_logins = 0
    user.locked_until = None
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    ttl = timedelta(minutes=settings.session_ttl_minutes)
    session.execute(delete(UserSession).where(UserSession.expires_at <= now))
    session.add(UserSession(token_hash=token_hash(token), user_id=user.id, expires_at=now + ttl))
    session.add(_event("auth.login", str(user.id), user=user))
    session.commit()

    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    return UserOut.model_validate(user)


def _session_for(request: Request, session: Session) -> UserSession | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return session.scalar(
        select(UserSession).where(
            UserSession.token_hash == token_hash(token),
            UserSession.expires_at > datetime.now(UTC),
        )
    )


def current_user(request: Request, session: DbSession) -> User:
    """The logged-in user; 401 without a valid, unexpired session."""
    user_session = _session_for(request, session)
    if user_session is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, NOT_LOGGED_IN)
    return user_session.user


CurrentUser = Annotated[User, Depends(current_user)]


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(session: DbSession, request: Request, response: Response) -> None:
    """End the session on the server and clear the cookie. Without a session it does nothing."""
    user_session = _session_for(request, session)
    if user_session is not None:
        user = user_session.user
        session.delete(user_session)
        session.add(_event("auth.logout", str(user.id), user=user))
        session.commit()
    settings = _settings(request)
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax"
    )


@router.get(
    "/me",
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorOut, "description": "Not logged in"}},
)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
