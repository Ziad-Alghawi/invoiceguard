import hashlib
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from invoiceguard_api import invoices
from invoiceguard_api.models import AuditEvent, Invoice, InvoiceStatus
from invoiceguard_api.settings import Settings

XML = b'<?xml version="1.0" encoding="UTF-8"?>\n<Invoice xmlns="urn:oasis:ubl"/>\n'
FinishedInvoice = Callable[[str], dict[str, Any]]
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def upload(client: TestClient, filename: str, content: bytes) -> httpx2.Response:
    # The client's content type is ignored: the type is decided from the bytes.
    return client.post("/invoices", files={"file": (filename, content, "text/plain")})


def test_upload_xml_creates_received_invoice(
    client: TestClient, db_session: Session, settings: Settings
) -> None:
    response = upload(client, "rechnung.xml", XML)

    assert response.status_code == 202
    body = response.json()
    sha256 = hashlib.sha256(XML).hexdigest()
    # The response reflects the state before the background task ran.
    assert body["status"] == "received"
    assert body["status_reason"] is None
    assert body["source_type"] == "xml"
    assert body["original_filename"] == "rechnung.xml"
    assert body["sha256"] == sha256
    assert body["size_bytes"] == len(XML)
    assert response.headers["location"].endswith(f"/invoices/{body['id']}")

    invoice = db_session.get(Invoice, uuid.UUID(body["id"]))
    assert invoice is not None
    assert invoice.storage_path == f"{sha256[:2]}/{sha256}.xml"
    assert (settings.storage_dir / invoice.storage_path).read_bytes() == XML


def test_upload_writes_audit_event(client: TestClient, db_session: Session) -> None:
    invoice_id = upload(client, "rechnung.pdf", PDF).json()["id"]

    event = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "invoice.received")
    ).one()
    assert event.actor == "anonymous"
    assert event.action == "invoice.received"
    assert (event.entity_type, event.entity_id) == ("invoice", invoice_id)
    assert event.details == {
        "filename": "rechnung.pdf",
        "sha256": hashlib.sha256(PDF).hexdigest(),
        "size_bytes": len(PDF),
        "source_type": "pdf",
    }


def test_upload_pdf_strips_client_path(client: TestClient) -> None:
    response = upload(client, "..\\..\\scans\\rechnung.pdf", PDF)

    assert response.status_code == 202
    assert response.json()["source_type"] == "pdf"
    assert response.json()["original_filename"] == "rechnung.pdf"


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("rechnung.txt", b"Rechnung Nr. 1"),
        ("rechnung.xml", b"Rechnung Nr. 1"),
        ("rechnung.pdf", XML),
        ("rechnung.exe", b"MZ\x90\x00"),
    ],
)
def test_wrong_type_is_rejected_with_415(
    client: TestClient, db_session: Session, settings: Settings, filename: str, content: bytes
) -> None:
    response = upload(client, filename, content)

    assert response.status_code == 415
    assert db_session.scalar(select(func.count()).select_from(Invoice)) == 0
    assert not settings.storage_dir.exists()


def test_file_over_the_limit_is_rejected_with_413(
    client: TestClient, db_session: Session, settings: Settings
) -> None:
    response = upload(client, "rechnung.pdf", PDF + b"0" * settings.max_upload_bytes)

    assert response.status_code == 413
    assert response.json() == {"detail": f"File is larger than {settings.max_upload_bytes} bytes."}
    assert db_session.scalar(select(func.count()).select_from(Invoice)) == 0


def test_file_exactly_at_the_limit_is_accepted(client: TestClient, settings: Settings) -> None:
    content = PDF + b"0" * (settings.max_upload_bytes - len(PDF))

    assert upload(client, "rechnung.pdf", content).status_code == 202


def test_huge_request_is_rejected_before_the_body_is_read(client: TestClient) -> None:
    response = upload(client, "rechnung.pdf", PDF + b"0" * 200_000)

    assert response.status_code == 413
    assert "Request body is larger than" in response.json()["detail"]


def test_same_file_again_returns_409_with_existing_id(
    client: TestClient, db_session: Session
) -> None:
    first = upload(client, "rechnung.xml", XML).json()

    response = upload(client, "kopie.xml", XML)

    assert response.status_code == 409
    assert response.json()["detail"]["invoice_id"] == first["id"]
    assert db_session.scalar(select(func.count()).select_from(Invoice)) == 1
    received = select(func.count()).where(AuditEvent.action == "invoice.received")
    assert db_session.scalar(received) == 1


def test_parallel_duplicate_caught_by_unique_index_returns_409(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = upload(client, "rechnung.xml", XML).json()
    # Simulate the race: the pre-check misses the row another request inserted meanwhile.
    real_find = invoices._find_by_sha256
    calls: list[str] = []

    def find_missing_once(session: Session, sha256: str) -> uuid.UUID | None:
        calls.append(sha256)
        return None if len(calls) == 1 else real_find(session, sha256)

    monkeypatch.setattr(invoices, "_find_by_sha256", find_missing_once)

    response = upload(client, "rechnung.xml", XML)

    assert response.status_code == 409
    assert response.json()["detail"]["invoice_id"] == first["id"]


def test_missing_file_is_rejected_with_422(client: TestClient) -> None:
    assert client.post("/invoices").status_code == 422


def test_list_returns_newest_first(client: TestClient) -> None:
    ids = [
        upload(client, f"rechnung-{n}.xml", XML.replace(b"/>", f' n="{n}"/>'.encode())).json()["id"]
        for n in range(3)
    ]

    response = client.get("/invoices")

    assert response.status_code == 200
    assert [invoice["id"] for invoice in response.json()] == ids[::-1]


def test_list_supports_limit_and_offset(client: TestClient) -> None:
    ids = [
        upload(client, f"rechnung-{n}.xml", XML.replace(b"/>", f' n="{n}"/>'.encode())).json()["id"]
        for n in range(3)
    ]

    response = client.get("/invoices", params={"limit": 1, "offset": 1})

    assert [invoice["id"] for invoice in response.json()] == [ids[1]]


def test_list_rejects_limit_over_200(client: TestClient) -> None:
    assert client.get("/invoices", params={"limit": 201}).status_code == 422


def test_list_is_empty_without_invoices(client: TestClient) -> None:
    assert client.get("/invoices").json() == []


def test_detail_returns_the_invoice(client: TestClient, finished: FinishedInvoice) -> None:
    created = upload(client, "rechnung.xml", XML).json()

    # Processing has run meanwhile: everything but the status is unchanged.
    detail = finished(f"/invoices/{created['id']}")
    assert detail.pop("status") == "failed"
    assert "Unknown invoice format" in detail.pop("status_reason")
    assert detail.pop("checks") == []
    created.pop("status")
    created.pop("status_reason")
    assert detail == created


@pytest.mark.parametrize(
    ("sample", "filename", "status", "reason"),
    [
        ("ubl_xrechnung", "rechnung.xml", InvoiceStatus.READY, None),
        ("zugferd2_pdf", "rechnung.pdf", InvoiceStatus.READY, None),
        ("plain_pdf", "scan.pdf", InvoiceStatus.AWAITING_EXTRACTION, "LLM extraction"),
        ("zugferd1", "alt.xml", InvoiceStatus.FAILED, "ZUGFeRD 1.0"),
    ],
)
def test_upload_returns_202_then_processing_sets_the_status(
    client: TestClient,
    finished: FinishedInvoice,
    samples: dict[str, bytes],
    sample: str,
    filename: str,
    status: InvoiceStatus,
    reason: str | None,
) -> None:
    response = upload(client, filename, samples[sample])

    assert response.status_code == 202
    detail = finished(response.headers["location"])
    assert detail["status"] == status.value
    if reason is None:
        assert detail["status_reason"] is None
    else:
        assert reason in detail["status_reason"]


def test_detail_of_unknown_invoice_is_404(client: TestClient) -> None:
    response = client.get(f"/invoices/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Invoice not found."}


def test_detail_with_malformed_id_is_422(client: TestClient) -> None:
    assert client.get("/invoices/not-a-uuid").status_code == 422


def test_storage_path_is_not_exposed(client: TestClient, tmp_path: Path) -> None:
    body = upload(client, "rechnung.xml", XML).json()

    assert "storage_path" not in body
    assert str(tmp_path) not in str(body)
