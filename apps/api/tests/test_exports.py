"""DATEV-style export endpoints (ADR-013): login, no double export, fiscal years, audit."""

import hashlib
import threading
import time
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, select, text, update
from sqlalchemy.orm import Session

from conftest import REVIEWER_EMAIL, FinishedInvoice
from invoiceguard_api.auth import SESSION_COOKIE
from invoiceguard_api.main import create_app
from invoiceguard_api.models import (
    AuditEvent,
    DatevExport,
    FieldSource,
    Invoice,
    InvoiceField,
    InvoiceStatus,
    SourceType,
    User,
)
from invoiceguard_api.settings import Settings

EXPORTS = "/exports/datev"


def add_invoice(
    engine: Engine,
    number: str,
    issue_date: date = date(2026, 11, 5),
    rates: tuple[str | None, ...] = ("19",),
    status: InvoiceStatus = InvoiceStatus.APPROVED,
    gross: str = "119.00",
) -> str:
    """An invoice row with the fields an export reads, without processing."""
    sha256 = hashlib.sha256(number.encode()).hexdigest()
    document = {
        "BT-1": number,
        "BT-2": issue_date.isoformat(),
        "BT-3": "380",
        "BT-5": "EUR",
        "BT-27": "Müller Bürobedarf GmbH",
        "BT-112": gross,
    }
    with Session(engine) as session:
        invoice = Invoice(
            id=uuid.uuid4(),
            status=status,
            source_type=SourceType.XML,
            original_filename=f"{number}.xml",
            sha256=sha256,
            size_bytes=1,
            storage_path=f"{sha256[:2]}/{sha256}.xml",
        )
        session.add(invoice)
        session.flush()
        fields: list[tuple[str, int | None, str]] = [
            (code, None, value) for code, value in document.items()
        ]
        for line_no, rate in enumerate(rates, 1):
            fields.append(("BT-126", line_no, str(line_no)))
            if rate is not None:
                fields.append(("BT-152", line_no, rate))
        session.add_all(
            InvoiceField(
                invoice_id=invoice.id,
                code=code,
                line_no=line_no,
                value=value,
                source=FieldSource.XML,
            )
            for code, line_no, value in fields
        )
        session.commit()
        return str(invoice.id)


def export(client: TestClient) -> tuple[dict[str, object], str]:
    """Create an export and download its file; the file decoded from Windows-1252."""
    response = client.post(EXPORTS)
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    assert response.headers["location"] == body["file_url"]
    file = client.get(str(body["file_url"]))
    assert file.status_code == 200
    return body, file.content.decode("cp1252")


def booking_rows(csv: str) -> list[list[str]]:
    return [row.split(";") for row in csv.split("\r\n")[2:-1]]


def actions(db_session: Session, entity_id: str) -> list[str]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(AuditEvent.action)
            .where(AuditEvent.entity_id == entity_id)
            .order_by(AuditEvent.id)
        )
    )


def test_export_needs_a_login(anon_client: TestClient) -> None:
    assert anon_client.post(EXPORTS).status_code == 401
    assert anon_client.get(f"{EXPORTS}/{uuid.uuid4()}/file").status_code == 401


def test_nothing_to_export_is_409(client: TestClient, engine: Engine) -> None:
    for status in (InvoiceStatus.READY, InvoiceStatus.BLOCKED, InvoiceStatus.REJECTED):
        add_invoice(engine, f"N-{status.value}", status=status)

    response = client.post(EXPORTS)

    assert response.status_code == 409
    assert response.json()["detail"] == "No approved invoices are waiting for export."


def test_uploaded_and_approved_invoice_is_exported_once(
    client: TestClient,
    finished: FinishedInvoice,
    samples: dict[str, bytes],
    seeded: None,
    reviewer: User,
    db_session: Session,
) -> None:
    upload = client.post(
        "/invoices", files={"file": ("r.xml", samples["ubl_xrechnung"], "text/xml")}
    )
    invoice_id = finished(upload.headers["location"])["id"]
    assert client.post(f"/invoices/{invoice_id}/approve", json={}).status_code == 200

    body, csv = export(client)

    assert body["invoice_count"] == 1
    assert (body["without_tax_key"], body["remaining"]) == (0, 0)
    assert (body["date_from"], body["date_to"]) == ("2026-11-05", "2026-11-05")
    assert str(body["filename"]).startswith("EXTF_Buchungsstapel_")
    [row] = booking_rows(csv)
    assert row[:11] == [
        "5137,23",
        '"H"',
        '"EUR"',
        "",
        "",
        "",
        "70000",
        "4900",
        '"9"',
        "0511",
        '"2026-IT-0815"',
    ]
    assert row[13] == '"Demo IT-Service GmbH"'
    assert csv.startswith('"EXTF";700;21;"Buchungsstapel";13;')
    assert ";1001;1;20260101;4;20260105;" not in csv
    assert ";1001;1;20260101;4;20261105;20261105;" in csv

    db_session.expire_all()
    stored = db_session.get(Invoice, uuid.UUID(invoice_id))
    assert stored is not None
    assert str(stored.datev_export_id) == body["id"]
    assert actions(db_session, invoice_id)[-1] == "invoice.exported"
    assert actions(db_session, str(body["id"])) == [
        "datev_export.created",
        "datev_export.downloaded",
    ]
    created = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "datev_export.created")
    ).one()
    assert (created.actor, created.user_id) == (REVIEWER_EMAIL, reviewer.id)
    assert created.details["invoice_ids"] == [invoice_id]

    # The same invoice never goes into a second file.
    assert client.post(EXPORTS).status_code == 409


def test_second_export_holds_only_new_invoices(client: TestClient, engine: Engine) -> None:
    add_invoice(engine, "A-1")
    _, first = export(client)
    add_invoice(engine, "B-2")

    body, second = export(client)

    assert body["invoice_count"] == 1
    assert '"A-1"' in first
    assert '"B-2"' in second
    assert '"A-1"' not in second


def test_only_approved_invoices_are_exported(client: TestClient, engine: Engine) -> None:
    add_invoice(engine, "OK-1")
    for status in (InvoiceStatus.READY, InvoiceStatus.BLOCKED, InvoiceStatus.REJECTED):
        add_invoice(engine, f"NO-{status.value}", status=status)

    body, csv = export(client)

    assert body["invoice_count"] == 1
    assert [row[10] for row in booking_rows(csv)] == ['"OK-1"']


def test_one_fiscal_year_per_file(client: TestClient, engine: Engine) -> None:
    add_invoice(engine, "Y26-B", date(2026, 1, 10))
    add_invoice(engine, "Y25", date(2025, 12, 10))
    add_invoice(engine, "Y26-A", date(2026, 1, 9))

    first, csv_2025 = export(client)
    second, csv_2026 = export(client)

    assert (first["invoice_count"], first["remaining"]) == (1, 2)
    assert first["fiscal_year_start"] == "2025-01-01"
    assert [row[10] for row in booking_rows(csv_2025)] == ['"Y25"']
    assert (second["invoice_count"], second["remaining"]) == (2, 0)
    # Rows ordered by document date; the header's range is the first and last date.
    assert [row[10] for row in booking_rows(csv_2026)] == ['"Y26-A"', '"Y26-B"']
    assert ";20260101;4;20260109;20260110;" in csv_2026


def test_fiscal_year_can_start_in_another_month(
    settings: Settings, engine: Engine, session_token: str
) -> None:
    add_invoice(engine, "MAR", date(2026, 3, 31))
    add_invoice(engine, "APR", date(2026, 4, 1))
    april = settings.model_copy(update={"datev_fiscal_year_start_month": 4})
    with TestClient(create_app(april)) as client:
        client.cookies.set(SESSION_COOKIE, session_token)
        body, csv = export(client)

    assert body["fiscal_year_start"] == "2025-04-01"
    assert [row[10] for row in booking_rows(csv)] == ['"MAR"']


@pytest.mark.parametrize(
    "rates",
    [("19", "7"), ("0",), ("19", None), ()],
    ids=["mixed", "unconfigured", "line-without-rate", "no-lines"],
)
def test_no_single_configured_rate_means_no_tax_key(
    client: TestClient, engine: Engine, rates: tuple[str | None, ...]
) -> None:
    add_invoice(engine, "T-1", rates=rates)

    body, csv = export(client)

    assert body["without_tax_key"] == 1
    [row] = booking_rows(csv)
    assert row[8] == '""'


def test_rate_with_decimals_finds_its_key(client: TestClient, engine: Engine) -> None:
    add_invoice(engine, "T-7", rates=("7.00", "7"))

    _, csv = export(client)

    assert booking_rows(csv)[0][8] == '"8"'


def test_accounts_and_numbers_come_from_settings(
    settings: Settings, engine: Engine, session_token: str
) -> None:
    add_invoice(engine, "S-1")
    custom = settings.model_copy(
        update={
            "datev_advisor_number": 29098,
            "datev_client_number": 55003,
            "datev_creditor_account": "70001",
            "datev_expense_account": "3400",
            "datev_tax_keys": {Decimal(19): "401"},
            "datev_chart_of_accounts": "04",
        }
    )
    with TestClient(create_app(custom)) as client:
        client.cookies.set(SESSION_COOKIE, session_token)
        _, csv = export(client)

    assert ";29098;55003;" in csv
    assert ';"04";' in csv.split("\r\n")[0]
    assert booking_rows(csv)[0][6:9] == ["70001", "3400", '"401"']


def test_tax_keys_are_read_as_json_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", database_url)
    monkeypatch.setenv("INVOICEGUARD_DATEV_TAX_KEYS", '{"19": "9", "7.0": "8", "0": "0"}')

    assert Settings().datev_tax_keys == {Decimal(19): "9", Decimal(7): "8", Decimal(0): "0"}


def test_download_again_is_the_same_file_and_audited(
    client: TestClient, engine: Engine, db_session: Session
) -> None:
    add_invoice(engine, "D-1")
    body, csv = export(client)

    again = client.get(str(body["file_url"]))

    assert again.content.decode("cp1252") == csv
    assert again.headers["content-type"] == "text/csv; charset=windows-1252"
    assert again.headers["content-disposition"].startswith(
        f'attachment; filename="{body["filename"]}"'
    )
    assert actions(db_session, str(body["id"])) == [
        "datev_export.created",
        "datev_export.downloaded",
        "datev_export.downloaded",
    ]


def test_unknown_export_is_404(client: TestClient) -> None:
    assert client.get(f"{EXPORTS}/{uuid.uuid4()}/file").status_code == 404


def test_an_invoice_taken_by_a_parallel_export_is_not_exported_again(
    client: TestClient, engine: Engine, reviewer: User
) -> None:
    """The export waits for the row lock of the other export, then sees the invoice as taken."""
    invoice_id = add_invoice(engine, "P-1")
    results: list[int] = []
    with engine.connect() as connection, connection.begin():
        connection.execute(text("SELECT id FROM invoices FOR UPDATE"))
        racer = threading.Thread(target=lambda: results.append(client.post(EXPORTS).status_code))
        racer.start()
        time.sleep(0.3)  # let the request reach the lock; either order ends the same
        other_id = uuid.uuid4()
        connection.execute(
            insert(DatevExport).values(
                id=other_id,
                user_id=reviewer.id,
                invoice_count=1,
                fiscal_year_start=date(2026, 1, 1),
                date_from=date(2026, 11, 5),
                date_to=date(2026, 11, 5),
                filename="other.csv",
                content=b"",
            )
        )
        connection.execute(
            update(Invoice)
            .where(Invoice.id == uuid.UUID(invoice_id))
            .values(datev_export_id=other_id)
        )
    racer.join(timeout=10)

    assert results == [409]
