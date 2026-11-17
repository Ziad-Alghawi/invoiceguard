"""The processing graph (ADR-015): every run pauses at review, only a resumed decision writes
`approved` or `rejected`, pauses survive restarts, and decisions on one invoice happen once."""

import hashlib
import threading
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.runnables import RunnableConfig
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from conftest import REVIEWER_EMAIL, FinishedInvoice, poll_until_done
from fakes import FakeLLMClient, reply_text
from invoiceguard_api import demo, processing
from invoiceguard_api.auth import SESSION_COOKIE
from invoiceguard_api.checks import KositValidator
from invoiceguard_api.db import make_session_factory
from invoiceguard_api.extraction import PdfExtractor
from invoiceguard_api.main import create_app, make_extractor
from invoiceguard_api.models import AuditEvent, Invoice, InvoiceStatus, SourceType, User
from invoiceguard_api.processing import (
    Decision,
    Graph,
    Services,
    StaleDecision,
    apply_decision,
    paused_for_review,
)
from invoiceguard_api.settings import Settings
from invoiceguard_api.storage import FileStorage

NO_VALIDATOR = KositValidator(None, 1.0)
DECISIONS = ["invoice.approved", "invoice.rejected", "invoice.override"]


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture
def storage(settings: Settings) -> FileStorage:
    return FileStorage(settings.storage_dir)


@pytest.fixture
def services(session_factory: sessionmaker[Session], storage: FileStorage) -> Services:
    return Services(session_factory, storage, NO_VALIDATOR, None)


@pytest.fixture
def graph(session_factory: sessionmaker[Session]) -> Iterator[Graph]:
    """The compiled graph on a checkpointer connection of its own, to look at threads."""
    with processing._open_graph(session_factory) as compiled:
        yield compiled


def config(invoice_id: uuid.UUID | str) -> RunnableConfig:
    return {"configurable": {"thread_id": str(invoice_id)}}


def add_invoice(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    content: bytes,
    source_type: SourceType = SourceType.XML,
    status: InvoiceStatus = InvoiceStatus.RECEIVED,
) -> uuid.UUID:
    """An invoice row with its stored file, without processing and without a thread."""
    sha256 = hashlib.sha256(content).hexdigest()
    invoice = Invoice(
        id=uuid.uuid4(),
        status=status,
        source_type=source_type,
        original_filename=f"rechnung.{source_type.value}",
        sha256=sha256,
        size_bytes=len(content),
        storage_path=storage.save(sha256, source_type.value, content),
    )
    with session_factory() as session:
        session.add(invoice)
        session.commit()
    return invoice.id


def processed(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    content: bytes,
    source_type: SourceType = SourceType.XML,
) -> uuid.UUID:
    invoice_id = add_invoice(session_factory, storage, content, source_type)
    processing.process_invoice(session_factory, storage, NO_VALIDATOR, None, invoice_id)
    return invoice_id


def status_of(db_session: Session, invoice_id: uuid.UUID | str) -> InvoiceStatus:
    db_session.expire_all()
    invoice = db_session.get(Invoice, uuid.UUID(str(invoice_id)))
    assert invoice is not None
    return invoice.status


def decision_events(db_session: Session, invoice_id: uuid.UUID | str) -> list[AuditEvent]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.entity_id == str(invoice_id), AuditEvent.action.in_(DECISIONS))
            .order_by(AuditEvent.id)
        )
    )


def decision(
    reviewer: User, action: str, status_before: str, reason: str | None = None
) -> Decision:
    return {
        "action": "approve" if action == "approve" else "reject",
        "user_id": str(reviewer.id),
        "actor": reviewer.email,
        "status_before": status_before,
        "reason": reason,
    }


def upload(client: TestClient, finished: FinishedInvoice, content: bytes) -> str:
    response = client.post("/invoices", files={"file": ("rechnung.xml", content, "text/plain")})
    assert response.status_code == 202, response.text
    invoice_id: str = finished(response.headers["location"])["id"]
    return invoice_id


# --- The shape of the graph ---------------------------------------------------------------------


def test_decide_is_reached_only_through_review() -> None:
    edges = processing.GRAPH.compile().get_graph().edges

    assert {edge.source for edge in edges if edge.target == "decide"} == {"review"}
    assert {edge.target for edge in edges if edge.source == "__start__"} == {
        "read",
        "extract",
        "review",
    }


# --- Every run pauses at review -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("sample", "source_type", "status"),
    [
        ("ubl_xrechnung", SourceType.XML, InvoiceStatus.READY),
        ("ubl_fraud_iban", SourceType.XML, InvoiceStatus.BLOCKED),
        ("broken", SourceType.XML, InvoiceStatus.FAILED),
        ("plain_pdf", SourceType.PDF, InvoiceStatus.AWAITING_EXTRACTION),
    ],
)
@pytest.mark.usefixtures("seeded")
def test_every_run_ends_paused_at_review(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    graph: Graph,
    db_session: Session,
    samples: dict[str, bytes],
    sample: str,
    source_type: SourceType,
    status: InvoiceStatus,
) -> None:
    invoice_id = add_invoice(session_factory, storage, samples[sample], source_type)

    processing.process_invoice(session_factory, storage, NO_VALIDATOR, None, invoice_id)

    assert status_of(db_session, invoice_id) is status
    assert paused_for_review(graph, invoice_id)
    # The fields are in their tables; the checkpoint keeps no copy of the invoice data.
    assert graph.get_state(config(invoice_id)).values.get("reading") is None


def test_running_the_graph_without_a_resume_cannot_approve(
    services: Services,
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    graph: Graph,
    db_session: Session,
    samples: dict[str, bytes],
) -> None:
    invoice_id = processed(session_factory, storage, samples["ubl_xrechnung"])

    # Continuing the thread without a resume value pauses at review again.
    graph.invoke(None, config(invoice_id), context=services)
    # A new run is always routed from START; it can start at review, never at decide.
    graph.invoke(
        {"invoice_id": str(invoice_id), "start": "review"}, config(invoice_id), context=services
    )

    assert status_of(db_session, invoice_id) is InvoiceStatus.READY
    assert paused_for_review(graph, invoice_id)
    assert decision_events(db_session, invoice_id) == []


# --- Decisions resume the thread ----------------------------------------------------------------


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_a_decision_resumes_the_paused_thread(
    client: TestClient,
    finished: FinishedInvoice,
    graph: Graph,
    samples: dict[str, bytes],
    seeded: None,
    action: str,
) -> None:
    invoice_id = upload(client, finished, samples["ubl_xrechnung"])
    assert paused_for_review(graph, uuid.UUID(invoice_id))

    response = client.post(f"/invoices/{invoice_id}/{action}", json={"reason": "Not ours."})

    assert response.status_code == 200
    state = graph.get_state(config(invoice_id))
    assert state.next == ()
    assert state.values["decision"]["action"] == action
    assert state.values["decision"]["actor"] == REVIEWER_EMAIL


def test_an_invoice_can_be_approved_after_an_api_restart(
    settings: Settings,
    engine: Engine,
    session_token: str,
    graph: Graph,
    db_session: Session,
    samples: dict[str, bytes],
    seeded: None,
) -> None:
    with TestClient(create_app(settings)) as first:
        first.cookies.set(SESSION_COOKIE, session_token)
        response = first.post(
            "/invoices", files={"file": ("rechnung.xml", samples["ubl_xrechnung"], "text/plain")}
        )
        invoice_id = poll_until_done(first, response.headers["location"])["id"]
    # The API is stopped while the thread waits at review.
    paused_at = graph.get_state(config(invoice_id)).config

    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set(SESSION_COOKIE, session_token)
        response = restarted.post(f"/invoices/{invoice_id}/approve", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    [event] = decision_events(db_session, invoice_id)
    assert (event.action, event.status_before, event.status_after) == (
        "invoice.approved",
        "ready",
        "approved",
    )
    # The approval resumed the thread that paused before the restart, not a new one.
    decided, reviewed, *_ = graph.get_state_history(config(invoice_id))
    assert reviewed.parent_config == paused_at
    assert decided.next == ()


@pytest.mark.parametrize("attempt", range(3))
def test_two_simultaneous_approvals_decide_once(
    client: TestClient,
    finished: FinishedInvoice,
    db_session: Session,
    samples: dict[str, bytes],
    seeded: None,
    attempt: int,
) -> None:
    invoice_id = upload(client, finished, samples["ubl_xrechnung"])
    start = threading.Barrier(2)
    codes: list[int] = []

    def approve() -> None:
        start.wait(timeout=5)
        codes.append(client.post(f"/invoices/{invoice_id}/approve", json={}).status_code)

    workers = [threading.Thread(target=approve) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)

    assert sorted(codes) == [200, 409]
    assert [event.action for event in decision_events(db_session, invoice_id)] == [
        "invoice.approved"
    ]
    assert status_of(db_session, invoice_id) is InvoiceStatus.APPROVED


def test_a_failed_resume_changes_nothing_and_can_be_repeated(
    client: TestClient,
    finished: FinishedInvoice,
    graph: Graph,
    db_session: Session,
    samples: dict[str, bytes],
    seeded: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoice_id = upload(client, finished, samples["ubl_xrechnung"])
    events = processing._decision_events
    failures = iter([RuntimeError("database gone")])

    def fail_once(*args: Any) -> list[AuditEvent]:
        if (error := next(failures, None)) is not None:
            raise error
        return events(*args)

    monkeypatch.setattr(processing, "_decision_events", fail_once)

    with pytest.raises(RuntimeError, match="database gone"):
        client.post(f"/invoices/{invoice_id}/reject", json={"reason": "First try."})

    assert status_of(db_session, invoice_id) is InvoiceStatus.READY
    assert decision_events(db_session, invoice_id) == []
    # The thread had resumed past review; the retry pauses it again and uses the new decision.
    assert not paused_for_review(graph, uuid.UUID(invoice_id))

    response = client.post(f"/invoices/{invoice_id}/reject", json={"reason": "Second try."})

    assert response.status_code == 200
    assert response.json()["status_reason"] == "Second try."
    [event] = decision_events(db_session, invoice_id)
    assert (event.action, event.reason) == ("invoice.rejected", "Second try.")


def test_decide_refuses_a_decision_on_a_changed_status(
    services: Services,
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    graph: Graph,
    db_session: Session,
    samples: dict[str, bytes],
    reviewer: User,
) -> None:
    invoice_id = processed(session_factory, storage, samples["ubl_xrechnung"])

    with pytest.raises(StaleDecision):
        apply_decision(services, invoice_id, decision(reviewer, "approve", "blocked"))

    assert status_of(db_session, invoice_id) is InvoiceStatus.READY
    assert decision_events(db_session, invoice_id) == []


# --- Recovery and reset -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [
        InvoiceStatus.READY,
        InvoiceStatus.BLOCKED,
        InvoiceStatus.FAILED,
        InvoiceStatus.AWAITING_EXTRACTION,
    ],
)
def test_startup_pauses_invoices_from_before_the_graph_at_review(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    graph: Graph,
    db_session: Session,
    samples: dict[str, bytes],
    reviewer: User,
    status: InvoiceStatus,
) -> None:
    invoice_id = add_invoice(session_factory, storage, samples["ubl_xrechnung"], status=status)
    assert graph.get_state(config(invoice_id)).values == {}

    processing.recover_unfinished(session_factory, storage, NO_VALIDATOR, None)

    assert paused_for_review(graph, invoice_id)
    # Pausing is not a status change: no audit event, nothing processed again.
    assert status_of(db_session, invoice_id) is status
    assert (
        db_session.scalars(select(AuditEvent).where(AuditEvent.entity_id == str(invoice_id))).all()
        == []
    )

    services = Services(session_factory, storage, NO_VALIDATOR, None)
    apply_decision(services, invoice_id, decision(reviewer, "reject", status.value, "Old one."))

    assert status_of(db_session, invoice_id) is InvoiceStatus.REJECTED


def test_demo_reset_replaces_the_threads(
    engine: Engine, settings: Settings, graph: Graph, db_session: Session
) -> None:
    session_factory = make_session_factory(engine)
    storage = FileStorage(settings.storage_dir)
    old = demo.reset_demo(session_factory, storage, NO_VALIDATOR, None)

    new = demo.reset_demo(session_factory, storage, NO_VALIDATOR, None)

    assert all(graph.get_state(config(invoice_id)).values == {} for invoice_id in old)
    assert all(paused_for_review(graph, invoice_id) for invoice_id in new)


# --- Extraction ---------------------------------------------------------------------------------


@pytest.fixture
def extractor(settings: Settings) -> PdfExtractor:
    built = make_extractor(settings, FakeLLMClient(reply_text()))
    assert built is not None
    return built


def test_an_unexpected_extraction_error_ends_in_failed_at_review(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    graph: Graph,
    db_session: Session,
    samples: dict[str, bytes],
    extractor: PdfExtractor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invoice_id = add_invoice(
        session_factory,
        storage,
        samples["text_pdf"],
        SourceType.PDF,
        InvoiceStatus.AWAITING_EXTRACTION,
    )

    def explode(*_: object) -> None:
        raise RuntimeError("model gone")

    monkeypatch.setattr(PdfExtractor, "extract", explode)

    processing.extract_invoice(session_factory, storage, extractor, invoice_id)

    db_session.expire_all()
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice is not None
    assert (invoice.status, invoice.status_reason) == (
        InvoiceStatus.FAILED,
        processing.INTERNAL_ERROR_REASON,
    )
    assert paused_for_review(graph, invoice_id)


def test_extraction_after_waiting_starts_a_new_run_on_the_thread(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    graph: Graph,
    db_session: Session,
    samples: dict[str, bytes],
    extractor: PdfExtractor,
    seeded: None,
) -> None:
    invoice_id = processed(session_factory, storage, samples["text_pdf"], SourceType.PDF)
    assert status_of(db_session, invoice_id) is InvoiceStatus.AWAITING_EXTRACTION

    processing.extract_invoice(session_factory, storage, extractor, invoice_id)

    assert status_of(db_session, invoice_id) is InvoiceStatus.READY
    assert paused_for_review(graph, invoice_id)
