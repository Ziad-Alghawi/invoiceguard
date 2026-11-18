"""Reopening a rejected invoice (ADR-016): any user, with a reason; the graph reads and checks
the invoice again on the current master data and pauses it at review. Approved invoices are
never reopened."""

import threading
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from conftest import REVIEWER_EMAIL, FinishedInvoice
from invoiceguard_api import processing
from invoiceguard_api.checks import KositValidator
from invoiceguard_api.db import make_session_factory
from invoiceguard_api.models import AuditEvent, Check, SupplierBankAccount, User
from invoiceguard_api.processing import (
    Decision,
    Graph,
    ReopenRefused,
    Services,
    apply_decision,
    paused_for_review,
)
from invoiceguard_api.settings import Settings
from invoiceguard_api.storage import FileStorage

REASON = "Rejected by mistake: the supplier confirmed the order by phone."
NO_VALIDATOR = KositValidator(None, 1.0)


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture
def graph(session_factory: sessionmaker[Session]) -> Iterator[Graph]:
    with processing._open_graph(session_factory) as compiled:
        yield compiled


def upload(client: TestClient, finished: FinishedInvoice, name: str, content: bytes) -> str:
    response = client.post("/invoices", files={"file": (name, content, "text/plain")})
    assert response.status_code == 202, response.text
    invoice_id: str = finished(response.headers["location"])["id"]
    return invoice_id


@pytest.fixture
def rejected_id(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes], seeded: None
) -> str:
    """The clean sample invoice, rejected by the reviewer."""
    invoice_id = upload(client, finished, "rechnung.xml", samples["ubl_xrechnung"])
    response = client.post(f"/invoices/{invoice_id}/reject", json={"reason": "Not ours."})
    assert response.json()["status"] == "rejected"
    return invoice_id


def events(db_session: Session, invoice_id: str) -> list[AuditEvent]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == invoice_id).order_by(AuditEvent.id)
        )
    )


def reopened(db_session: Session, invoice_id: str) -> list[AuditEvent]:
    return [event for event in events(db_session, invoice_id) if event.action == "invoice.reopened"]


def test_a_rejected_invoice_is_back_in_review_with_one_audit_row(
    client: TestClient, rejected_id: str, reviewer: User, graph: Graph, db_session: Session
) -> None:
    response = client.post(f"/invoices/{rejected_id}/reopen", json={"reason": f" {REASON} "})

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    [event] = reopened(db_session, rejected_id)
    assert (event.actor, event.user_id, event.reason) == (REVIEWER_EMAIL, reviewer.id, REASON)
    assert (event.status_before, event.status_after) == ("rejected", "processing")
    # After the decision row, only the rerun's own status change, as after an upload.
    last = events(db_session, rejected_id)[-1]
    assert (last.action, last.status_before, last.status_after) == (
        "invoice.status_changed",
        "processing",
        "ready",
    )
    assert paused_for_review(graph, uuid.UUID(rejected_id))
    # Back in review: it can be decided again.
    approved = client.post(f"/invoices/{rejected_id}/approve", json={})
    assert approved.json()["status"] == "approved"


def test_reopen_runs_the_checks_again_on_the_current_master_data(
    client: TestClient, rejected_id: str, db_session: Session
) -> None:
    db_session.expire_all()
    before = {check.type: check.created_at for check in db_session.scalars(select(Check))}
    # Since the rejection, the supplier's verified account changed in the registry.
    db_session.execute(update(SupplierBankAccount).values(iban="DE02120300000000202051"))
    db_session.commit()

    response = client.post(f"/invoices/{rejected_id}/reopen", json={"reason": REASON})

    assert response.json()["status"] == "blocked"
    detail = client.get(f"/invoices/{rejected_id}").json()
    failed = {check["type"] for check in detail["checks"] if check["status"] == "failed"}
    assert failed == {"iban"}
    db_session.expire_all()
    after = {check.type: check.created_at for check in db_session.scalars(select(Check))}
    assert after.keys() == before.keys()
    assert all(after[kind] > before[kind] for kind in before)
    assert detail["fields"]


def test_an_approver_can_reopen_too(
    approver_client: TestClient, rejected_id: str, db_session: Session
) -> None:
    response = approver_client.post(f"/invoices/{rejected_id}/reopen", json={"reason": REASON})

    assert response.status_code == 200
    assert len(reopened(db_session, rejected_id)) == 1


def test_an_approved_invoice_can_never_be_reopened(
    client: TestClient,
    finished: FinishedInvoice,
    samples: dict[str, bytes],
    seeded: None,
    db_session: Session,
) -> None:
    invoice_id = upload(client, finished, "rechnung.xml", samples["ubl_xrechnung"])
    client.post(f"/invoices/{invoice_id}/approve", json={})

    response = client.post(f"/invoices/{invoice_id}/reopen", json={"reason": REASON})

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Approved invoices cannot be reopened: they may already be in a DATEV export."
    )
    assert client.get(f"/invoices/{invoice_id}").json()["status"] == "approved"
    assert reopened(db_session, invoice_id) == []


def test_only_a_rejected_invoice_is_reopened(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes], seeded: None
) -> None:
    invoice_id = upload(client, finished, "rechnung.xml", samples["ubl_xrechnung"])

    response = client.post(f"/invoices/{invoice_id}/reopen", json={"reason": REASON})

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "The invoice is ready; only rejected invoices can be reopened."
    )


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "   "}])
def test_reopen_needs_a_reason(
    client: TestClient, rejected_id: str, db_session: Session, body: dict[str, str]
) -> None:
    response = client.post(f"/invoices/{rejected_id}/reopen", json=body)

    assert response.status_code == 422
    assert client.get(f"/invoices/{rejected_id}").json()["status"] == "rejected"
    assert reopened(db_session, rejected_id) == []


def test_reopen_of_an_unknown_invoice_is_404(client: TestClient) -> None:
    response = client.post(f"/invoices/{uuid.uuid4()}/reopen", json={"reason": REASON})

    assert response.status_code == 404


@pytest.mark.parametrize("attempt", range(3))
def test_two_reopens_at_the_same_time_reopen_once(
    client: TestClient,
    approver_client: TestClient,
    rejected_id: str,
    db_session: Session,
    attempt: int,
) -> None:
    start = threading.Barrier(2)
    codes: list[int] = []

    def reopen(user_client: TestClient) -> None:
        start.wait(timeout=5)
        url = f"/invoices/{rejected_id}/reopen"
        codes.append(user_client.post(url, json={"reason": REASON}).status_code)

    workers = [
        threading.Thread(target=reopen, args=(user_client,))
        for user_client in (client, approver_client)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)

    assert sorted(codes) == [200, 409]
    assert len(reopened(db_session, rejected_id)) == 1
    assert client.get(f"/invoices/{rejected_id}").json()["status"] == "ready"


def test_a_reopened_pdf_without_xml_waits_for_extraction_again(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes], graph: Graph
) -> None:
    invoice_id = upload(client, finished, "scan.pdf", samples["text_pdf"])
    client.post(f"/invoices/{invoice_id}/reject", json={"reason": "Not ours."})

    response = client.post(f"/invoices/{invoice_id}/reopen", json={"reason": REASON})

    # Without a model key it waits, as after its upload; with one, extraction runs next.
    assert response.json()["status"] == "awaiting_extraction"
    assert paused_for_review(graph, uuid.UUID(invoice_id))


def test_decide_refuses_to_reopen_anything_but_a_rejected_invoice(
    settings: Settings,
    session_factory: sessionmaker[Session],
    client: TestClient,
    finished: FinishedInvoice,
    samples: dict[str, bytes],
    seeded: None,
    reviewer: User,
    db_session: Session,
) -> None:
    invoice_id = upload(client, finished, "rechnung.xml", samples["ubl_xrechnung"])
    services = Services(session_factory, FileStorage(settings.storage_dir), NO_VALIDATOR, None)
    decision: Decision = {
        "action": "reopen",
        "user_id": str(reviewer.id),
        "actor": reviewer.email,
        "status_before": "ready",
        "reason": REASON,
    }

    with pytest.raises(ReopenRefused, match="is ready"):
        apply_decision(services, uuid.UUID(invoice_id), decision)

    detail = client.get(f"/invoices/{invoice_id}").json()
    assert detail["status"] == "ready"
    assert detail["checks"]
    assert reopened(db_session, invoice_id) == []
