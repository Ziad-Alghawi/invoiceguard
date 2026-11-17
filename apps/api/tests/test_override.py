"""Four-eyes override of a blocked invoice (ADR-016): a reviewer requests it with a reason, a
different user with the approver role confirms or declines it; each step is one audit row."""

import threading
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from conftest import (
    REVIEWER_EMAIL,
    FinishedInvoice,
    add_user,
    logged_in,
    poll_until_done,
    session_for,
)
from invoiceguard_api import processing
from invoiceguard_api.auth import SESSION_COOKIE
from invoiceguard_api.checks import KositValidator
from invoiceguard_api.db import make_session_factory
from invoiceguard_api.main import create_app
from invoiceguard_api.models import AuditEvent, InvoiceStatus, User, UserRole
from invoiceguard_api.processing import (
    Decision,
    ForbiddenDecision,
    Graph,
    Services,
    apply_decision,
    paused_for_review,
)
from invoiceguard_api.settings import Settings
from invoiceguard_api.storage import FileStorage

REASON = "IBAN change confirmed by phone with the supplier's accounting (Mr. Kurz)."
NO_VALIDATOR = KositValidator(None, 1.0)


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture
def graph(session_factory: sessionmaker[Session]) -> Iterator[Graph]:
    with processing._open_graph(session_factory) as compiled:
        yield compiled


@pytest.fixture
def blocked_id(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes], seeded: None
) -> str:
    response = client.post(
        "/invoices", files={"file": ("betrug.xml", samples["ubl_fraud_iban"], "text/plain")}
    )
    assert response.status_code == 202, response.text
    detail = finished(response.headers["location"])
    assert detail["status"] == "blocked"
    invoice_id: str = detail["id"]
    return invoice_id


@pytest.fixture
def requested_id(client: TestClient, blocked_id: str) -> str:
    """The blocked invoice after the reviewer (`client`) requested an override."""
    response = client.post(f"/invoices/{blocked_id}/override", json={"reason": REASON})
    assert response.status_code == 200, response.text
    return blocked_id


@pytest.fixture
def second_approver_client(
    client: TestClient, engine: Engine, reviewer_password_hash: str
) -> TestClient:
    other = add_user(
        engine, "zoe.koch@example.com", "Zoe Koch", reviewer_password_hash, UserRole.APPROVER
    )
    return logged_in(client, session_for(engine, other))


def events(
    db_session: Session, invoice_id: str, prefix: str = "invoice.override"
) -> list[AuditEvent]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_id == invoice_id, AuditEvent.action.like(f"{prefix}%"))
            .order_by(AuditEvent.id)
        )
    )


def status_of(client: TestClient, invoice_id: str) -> str:
    status: str = client.get(f"/invoices/{invoice_id}").json()["status"]
    return status


# --- Request ------------------------------------------------------------------------------------


def test_a_reviewer_requests_an_override_and_the_thread_waits_again(
    client: TestClient, blocked_id: str, reviewer: User, graph: Graph, db_session: Session
) -> None:
    response = client.post(f"/invoices/{blocked_id}/override", json={"reason": f"  {REASON} "})

    assert response.status_code == 200
    assert response.json()["status"] == "override_requested"
    assert response.json()["status_reason"] == REASON
    [event] = events(db_session, blocked_id)
    assert event.action == "invoice.override_requested"
    assert (event.actor, event.user_id, event.reason) == (REVIEWER_EMAIL, reviewer.id, REASON)
    assert (event.status_before, event.status_after) == ("blocked", "override_requested")
    assert event.details == {"failed_checks": ["iban"]}
    # The decision went through decide, which sent the thread back to review for the approver.
    assert paused_for_review(graph, uuid.UUID(blocked_id))


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "   "}])
def test_an_override_request_needs_a_reason(
    client: TestClient, blocked_id: str, body: dict[str, str]
) -> None:
    response = client.post(f"/invoices/{blocked_id}/override", json=body)

    assert response.status_code == 422
    assert status_of(client, blocked_id) == "blocked"


def test_only_a_blocked_invoice_gets_an_override(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes], seeded: None
) -> None:
    response = client.post(
        "/invoices", files={"file": ("ok.xml", samples["ubl_xrechnung"], "text/plain")}
    )
    ready_id = finished(response.headers["location"])["id"]

    response = client.post(f"/invoices/{ready_id}/override", json={"reason": REASON})

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "The invoice is ready; only blocked invoices can get an override."
    )


def test_a_requested_override_cannot_be_requested_or_approved_again(
    client: TestClient, requested_id: str
) -> None:
    assert client.post(f"/invoices/{requested_id}/override", json={"reason": "x"}).status_code == (
        409
    )
    response = client.post(f"/invoices/{requested_id}/approve", json={})
    assert response.status_code == 409
    assert "an approver confirms or declines it" in response.json()["detail"]


def test_a_requested_override_can_still_be_rejected(
    client: TestClient, requested_id: str, db_session: Session
) -> None:
    response = client.post(f"/invoices/{requested_id}/reject", json={"reason": "Fraud."})

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    [event] = events(db_session, requested_id, "invoice.rejected")
    assert (event.status_before, event.status_after) == ("override_requested", "rejected")


# --- Confirm and decline ------------------------------------------------------------------------


def test_an_approver_confirms_with_one_audit_row(
    approver_client: TestClient, requested_id: str, approver: User, db_session: Session
) -> None:
    response = approver_client.post(
        f"/invoices/{requested_id}/override/confirm", json={"reason": "Checked the call notes."}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    _, confirmed = events(db_session, requested_id)
    assert confirmed.action == "invoice.override_confirmed"
    assert (confirmed.actor, confirmed.user_id) == (approver.email, approver.id)
    assert confirmed.reason == "Checked the call notes."
    assert (confirmed.status_before, confirmed.status_after) == ("override_requested", "approved")
    assert confirmed.details == {"failed_checks": ["iban"]}


def test_an_approver_declines_back_to_blocked_with_one_audit_row(
    client: TestClient,
    approver_client: TestClient,
    requested_id: str,
    approver: User,
    graph: Graph,
    db_session: Session,
) -> None:
    response = approver_client.post(
        f"/invoices/{requested_id}/override/decline", json={"reason": "No call notes."}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    _, declined = events(db_session, requested_id)
    assert declined.action == "invoice.override_declined"
    assert (declined.user_id, declined.reason) == (approver.id, "No call notes.")
    assert (declined.status_before, declined.status_after) == ("override_requested", "blocked")
    # Blocked again and waiting at review: the reviewer can ask once more, or reject.
    assert paused_for_review(graph, uuid.UUID(requested_id))
    again = client.post(f"/invoices/{requested_id}/override", json={"reason": "New evidence."})
    assert again.json()["status"] == "override_requested"


@pytest.mark.parametrize("action", ["confirm", "decline"])
def test_a_reviewer_cannot_decide_an_override(
    client: TestClient,
    engine: Engine,
    reviewer_password_hash: str,
    requested_id: str,
    db_session: Session,
    action: str,
) -> None:
    other = add_user(engine, "ida.roth@example.com", "Ida Roth", reviewer_password_hash)
    other_reviewer = logged_in(client, session_for(engine, other))

    for decider in (client, other_reviewer):
        response = decider.post(f"/invoices/{requested_id}/override/{action}", json={"reason": "x"})
        assert response.status_code == 403
        assert response.json()["detail"] == (
            "Only a user with the approver role can decide an override."
        )

    assert status_of(client, requested_id) == "override_requested"
    assert [event.action for event in events(db_session, requested_id)] == [
        "invoice.override_requested"
    ]


@pytest.mark.parametrize("action", ["confirm", "decline"])
def test_the_requester_cannot_decide_their_own_override(
    approver_client: TestClient,
    second_approver_client: TestClient,
    blocked_id: str,
    db_session: Session,
    action: str,
) -> None:
    # An approver may request an override too, but then another approver decides it.
    approver_client.post(f"/invoices/{blocked_id}/override", json={"reason": REASON})

    response = approver_client.post(
        f"/invoices/{blocked_id}/override/{action}", json={"reason": "Fine by me."}
    )

    assert response.status_code == 403
    assert "a different approver has to decide it" in response.json()["detail"]
    assert status_of(approver_client, blocked_id) == "override_requested"
    assert len(events(db_session, blocked_id)) == 1

    response = second_approver_client.post(
        f"/invoices/{blocked_id}/override/{action}", json={"reason": "Checked."}
    )
    assert response.status_code == 200


def test_decide_refuses_the_requester_and_reviewers_even_without_the_endpoint(
    settings: Settings,
    session_factory: sessionmaker[Session],
    requested_id: str,
    reviewer: User,
    db_session: Session,
) -> None:
    services = Services(session_factory, FileStorage(settings.storage_dir), NO_VALIDATOR, None)
    decision: Decision = {
        "action": "confirm_override",
        "user_id": str(reviewer.id),
        "actor": reviewer.email,
        "status_before": "override_requested",
        "reason": "Self-approval.",
    }

    with pytest.raises(ForbiddenDecision, match="is not an approver"):
        apply_decision(services, uuid.UUID(requested_id), decision)

    with db_session.begin():
        db_session.get_one(User, reviewer.id).role = UserRole.APPROVER
    with pytest.raises(ForbiddenDecision, match="requested this override"):
        apply_decision(services, uuid.UUID(requested_id), decision)

    assert len(events(db_session, requested_id)) == 1


@pytest.mark.parametrize("action", ["confirm", "decline"])
def test_only_a_requested_override_can_be_decided(
    approver_client: TestClient, blocked_id: str, action: str
) -> None:
    response = approver_client.post(
        f"/invoices/{blocked_id}/override/{action}", json={"reason": "x"}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "The invoice is blocked; only override_requested invoices can have an override decided."
    )


@pytest.mark.parametrize(("first", "second"), [("confirm", "confirm"), ("confirm", "decline")])
def test_two_approvers_at_the_same_time_decide_once(
    approver_client: TestClient,
    second_approver_client: TestClient,
    requested_id: str,
    db_session: Session,
    first: str,
    second: str,
) -> None:
    start = threading.Barrier(2)
    codes: list[int] = []

    def decide(decider: TestClient, action: str) -> None:
        start.wait(timeout=5)
        url = f"/invoices/{requested_id}/override/{action}"
        codes.append(decider.post(url, json={"reason": "Checked."}).status_code)

    workers = [
        threading.Thread(target=decide, args=(approver_client, first)),
        threading.Thread(target=decide, args=(second_approver_client, second)),
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)

    assert sorted(codes) == [200, 409]
    decided = events(db_session, requested_id)[1:]
    assert len(decided) == 1
    assert decided[0].action in {"invoice.override_confirmed", "invoice.override_declined"}


# --- Restarts -----------------------------------------------------------------------------------


def test_the_approver_decides_after_an_api_restart(
    settings: Settings,
    engine: Engine,
    session_token: str,
    approver: User,
    graph: Graph,
    db_session: Session,
    samples: dict[str, bytes],
    seeded: None,
) -> None:
    with TestClient(create_app(settings)) as first:
        first.cookies.set(SESSION_COOKIE, session_token)
        response = first.post(
            "/invoices", files={"file": ("betrug.xml", samples["ubl_fraud_iban"], "text/plain")}
        )
        invoice_id = poll_until_done(first, response.headers["location"])["id"]
        first.post(f"/invoices/{invoice_id}/override", json={"reason": REASON})
    paused_at = graph.get_state({"configurable": {"thread_id": invoice_id}}).config

    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set(SESSION_COOKIE, session_for(engine, approver))
        response = restarted.post(
            f"/invoices/{invoice_id}/override/confirm", json={"reason": "Checked."}
        )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert [event.action for event in events(db_session, invoice_id)] == [
        "invoice.override_requested",
        "invoice.override_confirmed",
    ]
    # The confirmation resumed the pause from before the restart.
    _, reviewed, *_ = graph.get_state_history({"configurable": {"thread_id": invoice_id}})
    assert reviewed.parent_config == paused_at


def test_a_lost_pause_is_restored_and_the_requester_still_comes_from_the_audit_log(
    settings: Settings,
    session_factory: sessionmaker[Session],
    approver_client: TestClient,
    requested_id: str,
    reviewer: User,
    graph: Graph,
) -> None:
    processing.delete_threads(session_factory, [uuid.UUID(requested_id)])
    storage = FileStorage(settings.storage_dir)

    processing.recover_unfinished(session_factory, storage, NO_VALIDATOR, None)

    assert paused_for_review(graph, uuid.UUID(requested_id))
    services = Services(session_factory, storage, NO_VALIDATOR, None)
    with pytest.raises(ForbiddenDecision):
        apply_decision(
            services,
            uuid.UUID(requested_id),
            {
                "action": "decline_override",
                "user_id": str(reviewer.id),
                "actor": reviewer.email,
                "status_before": InvoiceStatus.OVERRIDE_REQUESTED.value,
                "reason": "x",
            },
        )
    response = approver_client.post(
        f"/invoices/{requested_id}/override/confirm", json={"reason": "Checked."}
    )
    assert response.json()["status"] == "approved"


def test_decide_leads_back_to_review_or_ends() -> None:
    edges = processing.GRAPH.compile().get_graph().edges

    assert {edge.target for edge in edges if edge.source == "decide"} == {"review", "__end__"}
    assert {edge.source for edge in edges if edge.target == "decide"} == {"review"}
