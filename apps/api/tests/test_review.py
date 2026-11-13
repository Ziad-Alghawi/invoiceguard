"""Review queue and decisions (ADR-012): list, detail, file, approve, reject, override, audit."""

import hashlib
import uuid
from collections.abc import Iterator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from conftest import REVIEWER_EMAIL, FinishedInvoice
from invoiceguard_api import invoices, main
from invoiceguard_api.auth import SESSION_COOKIE
from invoiceguard_api.models import (
    AuditEvent,
    FieldSource,
    Invoice,
    InvoiceField,
    InvoiceStatus,
    SourceType,
    User,
)
from invoiceguard_api.settings import Settings
from invoiceguard_api.storage import FileStorage


def upload(client: TestClient, finished: FinishedInvoice, filename: str, content: bytes) -> str:
    response = client.post("/invoices", files={"file": (filename, content, "text/plain")})
    assert response.status_code == 202, response.text
    detail = finished(response.headers["location"])
    invoice_id: str = detail["id"]
    return invoice_id


@pytest.fixture
def ready_id(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes], seeded: None
) -> str:
    """A clean XRechnung from a seeded supplier: `ready`."""
    return upload(client, finished, "rechnung.xml", samples["ubl_xrechnung"])


@pytest.fixture
def blocked_id(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes], seeded: None
) -> str:
    """The same supplier with a changed IBAN: `blocked` by the failed iban check."""
    return upload(client, finished, "betrug.xml", samples["ubl_fraud_iban"])


@pytest.fixture
def quiet_client(
    settings: Settings, engine: Engine, session_token: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A logged-in client whose app does not resume `received` or `processing` invoices on
    startup, so such invoices stay as the test created them."""
    monkeypatch.setattr(main, "recover_unfinished", lambda *_: None)
    with TestClient(main.create_app(settings)) as test_client:
        test_client.cookies.set(SESSION_COOKIE, session_token)
        yield test_client


def add_invoice(engine: Engine, status: InvoiceStatus, content: bytes = b"<x/>") -> str:
    """An invoice row in any status, without processing."""
    sha256 = hashlib.sha256(content + status.value.encode()).hexdigest()
    with Session(engine, expire_on_commit=False) as session:
        invoice = Invoice(
            id=uuid.uuid4(),
            status=status,
            source_type=SourceType.XML,
            original_filename="rechnung.xml",
            sha256=sha256,
            size_bytes=len(content),
            storage_path=f"{sha256[:2]}/{sha256}.xml",
        )
        session.add(invoice)
        session.commit()
        return str(invoice.id)


def review_events(db_session: Session, invoice_id: str) -> list[AuditEvent]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.entity_id == invoice_id,
                AuditEvent.action.in_(["invoice.approved", "invoice.rejected", "invoice.override"]),
            )
            .order_by(AuditEvent.id)
        )
    )


def status_of(client: TestClient, invoice_id: str) -> str:
    status: str = client.get(f"/invoices/{invoice_id}").json()["status"]
    return status


# --- Approve ----------------------------------------------------------------------------------


def test_approve_ready_invoice(
    client: TestClient, ready_id: str, reviewer: User, db_session: Session
) -> None:
    response = client.post(f"/invoices/{ready_id}/approve", json={})

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["status_reason"] is None
    [event] = review_events(db_session, ready_id)
    assert event.action == "invoice.approved"
    assert (event.actor, event.user_id) == (REVIEWER_EMAIL, reviewer.id)
    assert (event.status_before, event.status_after, event.reason) == ("ready", "approved", None)


def test_approve_blocked_invoice_without_override_is_refused(
    client: TestClient, blocked_id: str, db_session: Session
) -> None:
    response = client.post(f"/invoices/{blocked_id}/approve", json={})

    assert response.status_code == 409
    assert "blocked by failed checks (iban)" in response.json()["detail"]
    assert "override reason" in response.json()["detail"]
    assert status_of(client, blocked_id) == "blocked"
    assert review_events(db_session, blocked_id) == []


@pytest.mark.parametrize("reason", ["", "   "])
def test_blank_override_reason_is_422(client: TestClient, blocked_id: str, reason: str) -> None:
    response = client.post(f"/invoices/{blocked_id}/approve", json={"override_reason": reason})

    assert response.status_code == 422
    assert status_of(client, blocked_id) == "blocked"


def test_approve_blocked_invoice_with_override(
    client: TestClient, blocked_id: str, reviewer: User, db_session: Session
) -> None:
    reason = "  IBAN change confirmed by phone with the supplier's accounting (Mr. Kurz).  "

    response = client.post(f"/invoices/{blocked_id}/approve", json={"override_reason": reason})

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["status_reason"] == reason.strip()
    override, approved = review_events(db_session, blocked_id)
    assert override.action == "invoice.override"
    assert (override.status_before, override.status_after) == ("blocked", "approved")
    assert override.reason == reason.strip()
    assert override.details == {"failed_checks": ["iban"]}
    assert override.user_id == reviewer.id
    assert approved.action == "invoice.approved"
    assert (approved.status_before, approved.status_after) == ("blocked", "approved")
    assert approved.reason == reason.strip()


def test_override_on_a_ready_invoice_is_refused(client: TestClient, ready_id: str) -> None:
    response = client.post(
        f"/invoices/{ready_id}/approve", json={"override_reason": "just because"}
    )

    assert response.status_code == 409
    assert "no failed checks to override" in response.json()["detail"]
    assert status_of(client, ready_id) == "ready"


@pytest.mark.parametrize(
    "status",
    [
        InvoiceStatus.RECEIVED,
        InvoiceStatus.PROCESSING,
        InvoiceStatus.AWAITING_EXTRACTION,
        InvoiceStatus.FAILED,
        InvoiceStatus.APPROVED,
        InvoiceStatus.REJECTED,
    ],
)
def test_only_ready_or_blocked_invoices_can_be_approved(
    quiet_client: TestClient, engine: Engine, db_session: Session, status: InvoiceStatus
) -> None:
    invoice_id = add_invoice(engine, status)

    response = quiet_client.post(f"/invoices/{invoice_id}/approve", json={"override_reason": "x"})

    assert response.status_code == 409
    assert response.json()["detail"].startswith(f"The invoice is {status.value};")
    assert status_of(quiet_client, invoice_id) == status.value
    assert review_events(db_session, invoice_id) == []


def test_approving_twice_is_refused(client: TestClient, ready_id: str) -> None:
    assert client.post(f"/invoices/{ready_id}/approve", json={}).status_code == 200

    assert client.post(f"/invoices/{ready_id}/approve", json={}).status_code == 409


# --- Reject -----------------------------------------------------------------------------------


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "  "}])
def test_reject_needs_a_reason(client: TestClient, ready_id: str, body: dict[str, str]) -> None:
    response = client.post(f"/invoices/{ready_id}/reject", json=body)

    assert response.status_code == 422
    assert status_of(client, ready_id) == "ready"


def test_reject_blocked_invoice(
    client: TestClient, blocked_id: str, reviewer: User, db_session: Session
) -> None:
    response = client.post(
        f"/invoices/{blocked_id}/reject", json={"reason": "IBAN changed without notice."}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["status_reason"] == "IBAN changed without notice."
    [event] = review_events(db_session, blocked_id)
    assert event.action == "invoice.rejected"
    assert (event.actor, event.user_id) == (REVIEWER_EMAIL, reviewer.id)
    assert (event.status_before, event.status_after) == ("blocked", "rejected")
    assert event.reason == "IBAN changed without notice."


@pytest.mark.parametrize("status", [InvoiceStatus.FAILED, InvoiceStatus.AWAITING_EXTRACTION])
def test_failed_or_waiting_invoices_can_be_rejected(
    client: TestClient, engine: Engine, status: InvoiceStatus
) -> None:
    invoice_id = add_invoice(engine, status)

    response = client.post(f"/invoices/{invoice_id}/reject", json={"reason": "Not ours."})

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


@pytest.mark.parametrize(
    "status",
    [
        InvoiceStatus.RECEIVED,
        InvoiceStatus.PROCESSING,
        InvoiceStatus.APPROVED,
        InvoiceStatus.REJECTED,
    ],
)
def test_reject_is_refused_while_processing_or_after_a_decision(
    quiet_client: TestClient, engine: Engine, status: InvoiceStatus
) -> None:
    invoice_id = add_invoice(engine, status)

    response = quiet_client.post(f"/invoices/{invoice_id}/reject", json={"reason": "Not ours."})

    assert response.status_code == 409
    assert status_of(quiet_client, invoice_id) == status.value


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_decision_on_unknown_invoice_is_404(client: TestClient, action: str) -> None:
    response = client.post(f"/invoices/{uuid.uuid4()}/{action}", json={"reason": "x"})

    assert response.status_code == 404


# --- Audit history ----------------------------------------------------------------------------


def test_audit_history_shows_upload_processing_and_decision(
    client: TestClient, blocked_id: str
) -> None:
    client.post(f"/invoices/{blocked_id}/approve", json={"override_reason": "Confirmed by phone."})

    history = client.get(f"/invoices/{blocked_id}/audit").json()

    steps = [
        (event["action"], event["actor"], event["status_before"], event["status_after"])
        for event in history
    ]
    assert steps == [
        ("invoice.received", REVIEWER_EMAIL, None, None),
        ("invoice.status_changed", "system", "received", "processing"),
        ("invoice.status_changed", "system", "processing", "blocked"),
        ("invoice.override", REVIEWER_EMAIL, "blocked", "approved"),
        ("invoice.approved", REVIEWER_EMAIL, "blocked", "approved"),
    ]
    assert history[2]["reason"] == "Failed checks: iban."
    assert history[3]["reason"] == "Confirmed by phone."
    assert [event["id"] for event in history] == sorted(event["id"] for event in history)


def test_audit_history_of_unknown_invoice_is_404(client: TestClient) -> None:
    assert client.get(f"/invoices/{uuid.uuid4()}/audit").status_code == 404


@pytest.mark.parametrize(
    "statement",
    ["UPDATE audit_events SET reason = 'changed'", "DELETE FROM audit_events"],
)
def test_audit_log_is_append_only(
    client: TestClient, ready_id: str, engine: Engine, statement: str
) -> None:
    with pytest.raises(DBAPIError, match="audit_events is append-only"), engine.begin() as conn:
        conn.execute(text(statement))


# --- Queue, detail and file -------------------------------------------------------------------


def test_list_filters_by_status_and_counts(
    client: TestClient, ready_id: str, blocked_id: str, engine: Engine
) -> None:
    failed_id = add_invoice(engine, InvoiceStatus.FAILED)

    queue = client.get("/invoices", params={"status": ["ready", "blocked"]})
    blocked = client.get("/invoices", params={"status": "blocked"})
    everything = client.get("/invoices")

    assert {invoice["id"] for invoice in queue.json()} == {ready_id, blocked_id}
    assert queue.headers["x-total-count"] == "2"
    assert [invoice["id"] for invoice in blocked.json()] == [blocked_id]
    assert {invoice["id"] for invoice in everything.json()} == {ready_id, blocked_id, failed_id}
    assert everything.headers["x-total-count"] == "3"


def test_list_pages_keep_the_total(client: TestClient, engine: Engine) -> None:
    ids = {add_invoice(engine, InvoiceStatus.READY, str(n).encode()) for n in range(3)}

    first = client.get("/invoices", params={"limit": 2})
    second = client.get("/invoices", params={"limit": 2, "offset": 2})

    assert len(first.json()) == 2
    assert len(second.json()) == 1
    assert first.headers["x-total-count"] == second.headers["x-total-count"] == "3"
    assert {invoice["id"] for invoice in first.json() + second.json()} == ids


def test_list_rejects_unknown_status(client: TestClient) -> None:
    assert client.get("/invoices", params={"status": "paid"}).status_code == 422


def test_detail_lists_xml_fields_without_confidence(client: TestClient, ready_id: str) -> None:
    detail = client.get(f"/invoices/{ready_id}").json()

    fields = {(field["code"], field["line_no"]): field for field in detail["fields"]}
    iban = fields[("BT-84", None)]
    assert iban == {
        "code": "BT-84",
        "name": "payee_iban",
        "line_no": None,
        "value": "DE60123456780000000003",
        "source": "xml",
        "confidence": None,
        "low_confidence": False,
        "evidence": None,
    }
    assert fields[("BT-153", 1)]["name"] == "item_name"
    # Document terms first, then the lines in order.
    line_numbers = [field["line_no"] for field in detail["fields"]]
    assert line_numbers == sorted(line_numbers, key=lambda n: -1 if n is None else n)


def test_detail_flags_low_confidence_llm_fields(
    client: TestClient, engine: Engine, db_session: Session
) -> None:
    invoice_id = add_invoice(engine, InvoiceStatus.BLOCKED)
    evidence = {"page": 1, "snippet": "IBAN DE60 ..."}
    db_session.add_all(
        [
            InvoiceField(
                invoice_id=uuid.UUID(invoice_id),
                code="BT-84",
                value="DE60123456780000000003",
                source=FieldSource.LLM,
                confidence=Decimal("0.55"),
                evidence=evidence,
            ),
            InvoiceField(
                invoice_id=uuid.UUID(invoice_id),
                code="BT-1",
                value="2026-IT-0815",
                source=FieldSource.LLM,
                confidence=Decimal("0.8"),
                evidence={"page": 1, "snippet": "Rechnung Nr. 2026-IT-0815"},
            ),
        ]
    )
    db_session.commit()

    fields = {
        field["code"]: field for field in client.get(f"/invoices/{invoice_id}").json()["fields"]
    }

    assert fields["BT-84"]["low_confidence"] is True
    assert fields["BT-84"]["confidence"] == "0.550"
    assert fields["BT-84"]["evidence"] == evidence
    # At the threshold (0.8) is not low.
    assert fields["BT-1"]["low_confidence"] is False


def test_file_downloads_the_original_upload(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes], seeded: None
) -> None:
    content = samples["ubl_xrechnung"]
    invoice_id = upload(client, finished, "Rechnung März.xml", content)
    file_url = client.get(f"/invoices/{invoice_id}").json()["file_url"]

    response = client.get(file_url)

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == "application/xml"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"] == (
        "attachment; filename=\"Rechnung M_rz.xml\"; filename*=UTF-8''Rechnung%20M%C3%A4rz.xml"
    )


def test_download_name_cannot_break_the_header() -> None:
    header = invoices._attachment('a"b\\c\r\n.xml')

    assert header == "attachment; filename=\"a_b_c__.xml\"; filename*=UTF-8''a%22b%5Cc%0D%0A.xml"


def test_file_of_unknown_invoice_is_404(client: TestClient) -> None:
    assert client.get(f"/invoices/{uuid.uuid4()}/file").status_code == 404


def test_file_of_a_pdf_is_served_as_pdf(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    storage = FileStorage(settings.storage_dir)
    content = b"%PDF-1.7\n%%EOF\n"
    sha256 = hashlib.sha256(content).hexdigest()
    with Session(engine, expire_on_commit=False) as session:
        invoice = Invoice(
            id=uuid.uuid4(),
            status=InvoiceStatus.AWAITING_EXTRACTION,
            source_type=SourceType.PDF,
            original_filename="scan.pdf",
            sha256=sha256,
            size_bytes=len(content),
            storage_path=storage.save(sha256, "pdf", content),
        )
        session.add(invoice)
        session.commit()

    response = client.get(f"/invoices/{invoice.id}/file")

    assert response.content == content
    assert response.headers["content-type"] == "application/pdf"
