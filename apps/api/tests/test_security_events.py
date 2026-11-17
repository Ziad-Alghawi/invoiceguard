"""Security events (R2-4): failed logins, lockouts, refused role checks and self-approval
attempts are logged append-only, and only approvers can read them."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from conftest import REVIEWER_EMAIL, REVIEWER_PASSWORD, FinishedInvoice
from invoiceguard_api.models import SecurityEvent, SecuritySeverity, User

MAX_FAILURES = 5


def security_events(db_session: Session, event_type: str | None = None) -> list[SecurityEvent]:
    db_session.expire_all()
    query = select(SecurityEvent).order_by(SecurityEvent.id)
    if event_type is not None:
        query = query.where(SecurityEvent.type == event_type)
    return list(db_session.scalars(query))


def login(client: TestClient, email: str, password: str) -> int:
    response = client.post("/auth/login", json={"email": email, "password": password})
    return response.status_code


@pytest.fixture
def blocked_id(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes], seeded: None
) -> str:
    response = client.post(
        "/invoices", files={"file": ("betrug.xml", samples["ubl_fraud_iban"], "text/plain")}
    )
    invoice_id: str = finished(response.headers["location"])["id"]
    return invoice_id


# --- Logins -------------------------------------------------------------------------------------


def test_failed_logins_and_the_lockout_are_logged(
    anon_client: TestClient, reviewer: User, db_session: Session
) -> None:
    assert login(anon_client, "nobody@example.com", "whatever") == 401
    for _ in range(MAX_FAILURES):
        assert login(anon_client, REVIEWER_EMAIL, "wrong-password") == 401
    assert login(anon_client, REVIEWER_EMAIL, REVIEWER_PASSWORD) == 429

    events = security_events(db_session)
    assert [(event.type, event.details.get("reason")) for event in events] == [
        ("login_failed", "unknown_email"),
        *[("login_failed", "wrong_password")] * MAX_FAILURES,
        ("account_locked", f"{MAX_FAILURES} failed logins in a row"),
        ("login_failed", "locked"),
    ]
    unknown, *wrong, locked, while_locked = events
    assert (unknown.user_id, unknown.details["email"]) == (None, "nobody@example.com")
    assert unknown.severity is SecuritySeverity.LOW
    assert [event.details["failed_logins"] for event in wrong] == [1, 2, 3, 4, 5]
    assert {event.user_id for event in [*wrong, locked, while_locked]} == {reviewer.id}
    assert locked.severity is SecuritySeverity.MEDIUM
    # Never the password the attacker typed.
    assert all("wrong-password" not in str(event.details) for event in events)


def test_a_successful_login_logs_nothing(
    anon_client: TestClient, reviewer: User, db_session: Session
) -> None:
    assert login(anon_client, REVIEWER_EMAIL, REVIEWER_PASSWORD) == 200

    assert security_events(db_session) == []


# --- Refused decisions --------------------------------------------------------------------------


def test_a_reviewer_deciding_an_override_is_a_403_with_a_security_event(
    client: TestClient, blocked_id: str, reviewer: User, db_session: Session
) -> None:
    client.post(f"/invoices/{blocked_id}/override", json={"reason": "Phoned the supplier."})

    response = client.post(f"/invoices/{blocked_id}/override/confirm", json={"reason": "Mine."})

    assert response.status_code == 403
    [event] = security_events(db_session)
    assert (event.type, event.severity, event.user_id) == (
        "forbidden",
        SecuritySeverity.MEDIUM,
        reviewer.id,
    )
    assert event.details == {
        "method": "POST",
        "path": f"/invoices/{blocked_id}/override/confirm",
        "role": "reviewer",
        "required_role": "approver",
    }


@pytest.mark.parametrize("action", ["confirm", "decline"])
def test_self_approval_is_a_403_with_a_security_event(
    approver_client: TestClient,
    blocked_id: str,
    approver: User,
    db_session: Session,
    action: str,
) -> None:
    approver_client.post(f"/invoices/{blocked_id}/override", json={"reason": "Phoned them."})

    response = approver_client.post(
        f"/invoices/{blocked_id}/override/{action}", json={"reason": "Fine by me."}
    )

    assert response.status_code == 403
    [event] = security_events(db_session)
    assert (event.type, event.severity, event.user_id, str(event.invoice_id)) == (
        "self_approval_attempt",
        SecuritySeverity.HIGH,
        approver.id,
        blocked_id,
    )
    assert event.details["action"] == f"{action}_override"
    # The refusal released the invoice: another request goes through at once.
    status = approver_client.get(f"/invoices/{blocked_id}").json()["status"]
    assert status == "override_requested"


# --- Reading the log ----------------------------------------------------------------------------


def test_approvers_read_the_events_newest_first(
    anon_client: TestClient,
    approver_client: TestClient,
    reviewer: User,
    db_session: Session,
) -> None:
    login(anon_client, "nobody@example.com", "whatever")
    login(anon_client, REVIEWER_EMAIL, "wrong-password")

    response = approver_client.get("/security-events")

    assert response.status_code == 200
    assert response.headers["x-total-count"] == "2"
    newest, oldest = response.json()
    assert (newest["type"], newest["user_email"], newest["user_id"]) == (
        "login_failed",
        REVIEWER_EMAIL,
        str(reviewer.id),
    )
    assert newest["severity"] == "low"
    assert (oldest["user_email"], oldest["details"]["email"]) == (None, "nobody@example.com")
    assert newest["id"] > oldest["id"]


def test_the_list_filters_by_type_and_pages(
    anon_client: TestClient, approver_client: TestClient, reviewer: User
) -> None:
    for _ in range(MAX_FAILURES):
        login(anon_client, REVIEWER_EMAIL, "wrong-password")

    locked = approver_client.get("/security-events", params={"type": "account_locked"})
    page = approver_client.get("/security-events", params={"limit": 2, "offset": 1})
    both = approver_client.get(
        "/security-events", params={"type": ["account_locked", "login_failed"], "limit": 1}
    )

    assert [event["type"] for event in locked.json()] == ["account_locked"]
    assert locked.headers["x-total-count"] == "1"
    assert len(page.json()) == 2
    assert page.headers["x-total-count"] == str(MAX_FAILURES + 1)
    assert both.headers["x-total-count"] == str(MAX_FAILURES + 1)


def test_reviewers_cannot_read_the_events_and_the_attempt_is_logged(
    client: TestClient, reviewer: User, db_session: Session
) -> None:
    response = client.get("/security-events")

    assert response.status_code == 403
    [event] = security_events(db_session, "forbidden")
    assert (event.user_id, event.details["path"]) == (reviewer.id, "/security-events")


def test_the_events_need_a_login(anon_client: TestClient) -> None:
    assert anon_client.get("/security-events").status_code == 401


@pytest.mark.parametrize(
    "statement",
    ["UPDATE security_events SET type = 'changed'", "DELETE FROM security_events"],
)
def test_the_security_log_is_append_only(
    anon_client: TestClient, reviewer: User, engine: Engine, statement: str
) -> None:
    login(anon_client, REVIEWER_EMAIL, "wrong-password")

    with pytest.raises(DBAPIError, match="security_events is append-only"), engine.begin() as conn:
        conn.execute(text(statement))
