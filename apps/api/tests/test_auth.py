"""Login, logout, sessions and lockout (ADR-011), and that every invoice endpoint needs a login."""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from conftest import REVIEWER_EMAIL, REVIEWER_PASSWORD
from invoiceguard_api import seed_user
from invoiceguard_api.auth import SESSION_COOKIE, token_hash
from invoiceguard_api.main import create_app
from invoiceguard_api.models import AuditEvent, User, UserSession
from invoiceguard_api.settings import Settings, get_settings

SOME_ID = uuid.uuid4()
PROTECTED = [
    ("GET", "/invoices"),
    ("POST", "/invoices"),
    ("GET", f"/invoices/{SOME_ID}"),
    ("GET", f"/invoices/{SOME_ID}/file"),
    ("GET", f"/invoices/{SOME_ID}/audit"),
    ("POST", f"/invoices/{SOME_ID}/approve"),
    ("POST", f"/invoices/{SOME_ID}/reject"),
    ("GET", "/auth/me"),
]
MAX_FAILURES = 5


def login(client: TestClient, email: str, password: str) -> httpx2.Response:
    return client.post("/auth/login", json={"email": email, "password": password})


def events(db_session: Session, action: str) -> list[AuditEvent]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.id)
        )
    )


def reload(db_session: Session, user: User) -> User:
    db_session.expire_all()
    loaded = db_session.get(User, user.id)
    assert loaded is not None
    return loaded


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_without_login_every_invoice_endpoint_is_401(
    anon_client: TestClient, method: str, path: str
) -> None:
    response = anon_client.request(method, path)

    assert response.status_code == 401
    assert response.json() == {"detail": "Not logged in."}


def test_invalid_session_token_is_401(anon_client: TestClient, reviewer: User) -> None:
    anon_client.cookies.set(SESSION_COOKIE, "not-a-real-token")

    assert anon_client.get("/invoices").status_code == 401


def test_health_needs_no_login(anon_client: TestClient) -> None:
    assert anon_client.get("/health").status_code == 200


def test_login_sets_an_httponly_session_cookie(
    anon_client: TestClient, reviewer: User, db_session: Session
) -> None:
    response = login(anon_client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    assert response.status_code == 200
    assert response.json() == {
        "id": str(reviewer.id),
        "email": REVIEWER_EMAIL,
        "display_name": "Anna Becker",
    }
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    # Plain http in tests and dev; prod adds Secure (next test).
    assert "Secure" not in cookie
    # Only the hash of the token is stored.
    token = anon_client.cookies[SESSION_COOKIE]
    stored = db_session.scalars(select(UserSession)).one()
    assert stored.token_hash == token_hash(token) != token

    assert anon_client.get("/auth/me").json()["email"] == REVIEWER_EMAIL
    assert anon_client.get("/invoices").status_code == 200
    [event] = events(db_session, "auth.login")
    assert (event.actor, event.user_id) == (REVIEWER_EMAIL, reviewer.id)
    assert (event.entity_type, event.entity_id) == ("user", str(reviewer.id))


def test_login_cookie_is_secure_in_prod(settings: Settings, engine: Engine, reviewer: User) -> None:
    prod = settings.model_copy(update={"env": "prod"})

    with TestClient(create_app(prod)) as client:
        response = login(client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


def test_login_ignores_email_case_and_spaces(anon_client: TestClient, reviewer: User) -> None:
    response = login(anon_client, "  Anna.Becker@Example.COM ", REVIEWER_PASSWORD)

    assert response.status_code == 200


def test_wrong_password_is_401_and_audited(
    anon_client: TestClient, reviewer: User, db_session: Session
) -> None:
    response = login(anon_client, REVIEWER_EMAIL, "wrong-password")

    assert response.status_code == 401
    assert response.json() == {"detail": "Wrong email or password."}
    assert SESSION_COOKIE not in anon_client.cookies
    assert reload(db_session, reviewer).failed_logins == 1
    [event] = events(db_session, "auth.login_failed")
    # Not authenticated, so not attributed to the user; the password is never stored.
    assert (event.actor, event.user_id) == ("anonymous", None)
    assert (event.entity_id, event.reason) == (str(reviewer.id), "wrong_password")
    assert "wrong-password" not in str(event.details)


def test_unknown_email_gets_the_same_reply(
    anon_client: TestClient, reviewer: User, db_session: Session
) -> None:
    response = login(anon_client, "nobody@example.com", REVIEWER_PASSWORD)

    assert response.status_code == 401
    assert response.json() == {"detail": "Wrong email or password."}
    [event] = events(db_session, "auth.login_failed")
    assert (event.entity_id, event.reason) == ("unknown", "unknown_email")
    assert event.details == {"email": "nobody@example.com"}


def test_empty_credentials_are_422(anon_client: TestClient) -> None:
    assert login(anon_client, "", "").status_code == 422


def test_repeated_failures_lock_the_account(
    anon_client: TestClient, reviewer: User, db_session: Session
) -> None:
    for _ in range(MAX_FAILURES):
        assert login(anon_client, REVIEWER_EMAIL, "wrong-password").status_code == 401

    # Locked: even the right password is refused, and it is not checked.
    response = login(anon_client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    assert response.status_code == 429
    assert 0 < int(response.headers["retry-after"]) <= 15 * 60
    assert SESSION_COOKIE not in anon_client.cookies
    user = reload(db_session, reviewer)
    assert user.locked_until is not None
    assert user.locked_until > datetime.now(UTC)
    [locked] = events(db_session, "auth.locked")
    assert (locked.actor, locked.reason) == ("system", "5 failed logins in a row")
    reasons = [event.reason for event in events(db_session, "auth.login_failed")]
    assert reasons == ["wrong_password"] * MAX_FAILURES + ["locked"]


def test_login_works_again_after_the_lockout(
    anon_client: TestClient, reviewer: User, db_session: Session
) -> None:
    for _ in range(MAX_FAILURES):
        login(anon_client, REVIEWER_EMAIL, "wrong-password")
    db_session.execute(update(User).values(locked_until=datetime.now(UTC) - timedelta(seconds=1)))
    db_session.commit()

    response = login(anon_client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    assert response.status_code == 200
    user = reload(db_session, reviewer)
    assert (user.failed_logins, user.locked_until) == (0, None)


def test_successful_login_resets_the_failure_count(
    anon_client: TestClient, reviewer: User, db_session: Session
) -> None:
    for _ in range(MAX_FAILURES - 1):
        login(anon_client, REVIEWER_EMAIL, "wrong-password")
    assert login(anon_client, REVIEWER_EMAIL, REVIEWER_PASSWORD).status_code == 200

    # A new run of failures starts at zero, so one more is not a lockout.
    assert login(anon_client, REVIEWER_EMAIL, "wrong-password").status_code == 401
    assert reload(db_session, reviewer).locked_until is None


def test_logout_ends_the_session_on_the_server(
    client: TestClient, reviewer: User, session_token: str, db_session: Session
) -> None:
    response = client.post("/auth/logout")

    assert response.status_code == 204
    assert f'{SESSION_COOKIE}=""' in response.headers["set-cookie"]
    assert db_session.scalars(select(UserSession)).all() == []
    [event] = events(db_session, "auth.logout")
    assert (event.actor, event.user_id) == (REVIEWER_EMAIL, reviewer.id)
    # A copy of the old cookie is useless now.
    client.cookies.set(SESSION_COOKIE, session_token)
    assert client.get("/auth/me").status_code == 401


def test_logout_without_session_does_nothing(anon_client: TestClient, db_session: Session) -> None:
    assert anon_client.post("/auth/logout").status_code == 204
    assert events(db_session, "auth.logout") == []


def test_expired_session_is_401(client: TestClient, db_session: Session) -> None:
    db_session.execute(
        update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db_session.commit()

    assert client.get("/invoices").status_code == 401


def test_login_removes_expired_sessions(
    anon_client: TestClient, session_token: str, db_session: Session
) -> None:
    db_session.execute(
        update(UserSession).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    db_session.commit()

    login(anon_client, REVIEWER_EMAIL, REVIEWER_PASSWORD)

    db_session.expire_all()
    stored = db_session.scalars(select(UserSession.token_hash)).all()
    assert token_hash(session_token) not in stored
    assert len(stored) == 1


# --- Seeding users from the environment -------------------------------------------------------


def test_upsert_user_creates_then_resets_a_user(db_session: Session, engine: Engine) -> None:
    created = seed_user.upsert_user(db_session, "Bob@Example.com", "Bob", "first-password-1")
    db_session.commit()
    created.failed_logins = 3
    created.locked_until = datetime.now(UTC) + timedelta(minutes=5)
    db_session.commit()

    updated = seed_user.upsert_user(db_session, "bob@example.com", "Bob B.", "second-password")
    db_session.commit()

    assert updated.id == created.id
    assert (updated.email, updated.display_name) == ("bob@example.com", "Bob B.")
    assert (updated.failed_logins, updated.locked_until) == (0, None)
    assert updated.password_hash.startswith("$argon2id$")
    actions = [event.action for event in db_session.scalars(select(AuditEvent))]
    assert actions == ["user.created", "user.updated"]


def test_seeded_user_can_log_in(
    anon_client: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", database_url)
    monkeypatch.setenv("INVOICEGUARD_SEED_USER_EMAIL", "carla@example.com")
    monkeypatch.setenv("INVOICEGUARD_SEED_USER_PASSWORD", "a-long-demo-password")
    monkeypatch.setenv("INVOICEGUARD_SEED_USER_NAME", "Carla")
    get_settings.cache_clear()
    try:
        seed_user.main()
    finally:
        get_settings.cache_clear()

    response = login(anon_client, "carla@example.com", "a-long-demo-password")
    assert response.status_code == 200
    assert response.json()["display_name"] == "Carla"


def test_seed_user_refuses_a_short_password_without_printing_it(
    monkeypatch: pytest.MonkeyPatch, database_url: str, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", database_url)
    monkeypatch.setenv("INVOICEGUARD_SEED_USER_EMAIL", "dora@example.com")
    monkeypatch.setenv("INVOICEGUARD_SEED_USER_PASSWORD", "short-pw")
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as exit_info:
            seed_user.main()
    finally:
        get_settings.cache_clear()

    message = str(exit_info.value)
    assert "INVOICEGUARD_SEED_USER_PASSWORD" in message
    assert "short-pw" not in message


def test_seed_user_needs_email_and_password(
    monkeypatch: pytest.MonkeyPatch, database_url: str, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", database_url)
    monkeypatch.delenv("INVOICEGUARD_SEED_USER_EMAIL", raising=False)
    monkeypatch.delenv("INVOICEGUARD_SEED_USER_PASSWORD", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as exit_info:
            seed_user.main()
    finally:
        get_settings.cache_clear()

    assert "INVOICEGUARD_SEED_USER_EMAIL, INVOICEGUARD_SEED_USER_PASSWORD" in str(exit_info.value)
