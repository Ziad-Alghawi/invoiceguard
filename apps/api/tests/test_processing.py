import hashlib
import threading
import time
import uuid
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from invoiceguard_api import main, processing
from invoiceguard_api.checks import KositValidator
from invoiceguard_api.checks.model import Validation
from invoiceguard_api.db import make_session_factory
from invoiceguard_api.main import create_app
from invoiceguard_api.models import (
    AuditEvent,
    Check,
    FieldSource,
    Invoice,
    InvoiceField,
    InvoiceStatus,
    SourceType,
)
from invoiceguard_api.processing import process_invoice, recover_unfinished
from invoiceguard_api.settings import Settings
from invoiceguard_api.storage import FileStorage

# Without a validator URL the KoSIT check is skipped; the other checks run as usual.
NO_VALIDATOR = KositValidator(None, 1.0)


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return make_session_factory(engine)


@pytest.fixture
def storage(settings: Settings) -> FileStorage:
    return FileStorage(settings.storage_dir)


def add_invoice(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    content: bytes,
    source_type: SourceType,
    status: InvoiceStatus = InvoiceStatus.RECEIVED,
) -> uuid.UUID:
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


def load(db_session: Session, invoice_id: uuid.UUID) -> Invoice:
    db_session.expire_all()
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice is not None
    return invoice


def fields(db_session: Session, invoice_id: uuid.UUID) -> dict[tuple[str, int | None], str]:
    rows = db_session.scalars(select(InvoiceField).where(InvoiceField.invoice_id == invoice_id))
    return {(row.code, row.line_no): row.value for row in rows}


def status_changes(
    db_session: Session, invoice_id: uuid.UUID
) -> list[tuple[str | None, str | None]]:
    events = db_session.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.entity_id == str(invoice_id), AuditEvent.action == "invoice.status_changed"
        )
        .order_by(AuditEvent.id)
    )
    return [(event.status_before, event.status_after) for event in events]


@pytest.mark.parametrize(
    ("sample", "source_type", "status", "reason"),
    [
        ("cii_xrechnung", SourceType.XML, InvoiceStatus.READY, None),
        ("ubl_xrechnung", SourceType.XML, InvoiceStatus.READY, None),
        ("zugferd2_pdf", SourceType.PDF, InvoiceStatus.READY, None),
        ("zugferd1_pdf", SourceType.PDF, InvoiceStatus.FAILED, "ZUGFeRD 1.0 is not supported"),
        ("broken", SourceType.XML, InvoiceStatus.FAILED, "not well-formed"),
        ("xxe", SourceType.XML, InvoiceStatus.FAILED, "document type declaration"),
        ("plain_pdf", SourceType.PDF, InvoiceStatus.AWAITING_EXTRACTION, "LLM extraction"),
    ],
)
def test_each_sample_ends_in_the_expected_status(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    db_session: Session,
    samples: dict[str, bytes],
    sample: str,
    source_type: SourceType,
    status: InvoiceStatus,
    reason: str | None,
) -> None:
    invoice_id = add_invoice(session_factory, storage, samples[sample], source_type)

    process_invoice(session_factory, storage, NO_VALIDATOR, None, invoice_id)

    invoice = load(db_session, invoice_id)
    assert invoice.status is status
    if reason is None:
        assert invoice.status_reason is None
    else:
        assert reason in (invoice.status_reason or "")
    assert status_changes(db_session, invoice_id) == [
        ("received", "processing"),
        ("processing", status.value),
    ]
    assert bool(fields(db_session, invoice_id)) == (status is InvoiceStatus.READY)


def test_ready_invoice_stores_business_terms(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    db_session: Session,
    samples: dict[str, bytes],
) -> None:
    invoice_id = add_invoice(session_factory, storage, samples["cii_xrechnung"], SourceType.XML)

    process_invoice(session_factory, storage, NO_VALIDATOR, None, invoice_id)

    stored = fields(db_session, invoice_id)
    assert stored[("BT-1", None)] == "RE-2026-10417"
    assert stored[("BT-84", None)] == "DE17123456780000000001"
    assert stored[("BT-112", None)] == "436.14"
    assert stored[("BT-129", 1)] == "10"
    assert stored[("BT-153", 2)] == "Ordner DIN A4, 8 cm, blau"
    rows = db_session.scalars(select(InvoiceField).where(InvoiceField.invoice_id == invoice_id))
    assert {(row.source, row.confidence) for row in rows} == {(FieldSource.XML, None)}


def test_ready_event_records_syntax_and_warnings(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    db_session: Session,
    samples: dict[str, bytes],
) -> None:
    xml = samples["ubl_xrechnung"].replace(
        b"<cac:PaymentTerms>",
        b"<cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode>"
        b"<cac:PayeeFinancialAccount><cbc:ID>DE02120300000000202051</cbc:ID>"
        b"</cac:PayeeFinancialAccount></cac:PaymentMeans><cac:PaymentTerms>",
    )
    invoice_id = add_invoice(session_factory, storage, xml, SourceType.XML)

    process_invoice(session_factory, storage, NO_VALIDATOR, None, invoice_id)

    event = db_session.scalars(
        select(AuditEvent).where(AuditEvent.entity_id == str(invoice_id)).order_by(AuditEvent.id)
    ).all()[-1]
    assert event.actor == "system"
    assert (event.status_before, event.status_after, event.reason) == ("processing", "ready", None)
    assert event.details == {
        "syntax": "ubl",
        "warnings": ["multiple_payee_ibans: 2 found, stored the first"],
        # Unseeded database: supplier and order unknown (warnings), no validator (skipped).
        "checks": {
            "passed": 2,
            "warning": 4,
            "failed": 0,
            "skipped": 1,
            "failed_checks": [],
        },
    }


def test_processing_twice_is_harmless(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    db_session: Session,
    samples: dict[str, bytes],
) -> None:
    invoice_id = add_invoice(session_factory, storage, samples["ubl_xrechnung"], SourceType.XML)
    process_invoice(session_factory, storage, NO_VALIDATOR, None, invoice_id)
    first = fields(db_session, invoice_id)

    # A finished invoice is not claimed again.
    process_invoice(session_factory, storage, NO_VALIDATOR, None, invoice_id)
    assert len(status_changes(db_session, invoice_id)) == 2

    # A re-run (for example after a reset) replaces the fields instead of adding duplicates.
    with session_factory() as session:
        invoice = session.get(Invoice, invoice_id)
        assert invoice is not None
        invoice.status = InvoiceStatus.RECEIVED
        session.commit()
    process_invoice(session_factory, storage, NO_VALIDATOR, None, invoice_id)

    assert fields(db_session, invoice_id) == first
    assert load(db_session, invoice_id).status is InvoiceStatus.READY


def test_unknown_invoice_id_is_skipped(
    session_factory: sessionmaker[Session], storage: FileStorage, db_session: Session
) -> None:
    process_invoice(session_factory, storage, NO_VALIDATOR, None, uuid.uuid4())

    assert db_session.scalars(select(AuditEvent)).all() == []


def test_unexpected_error_ends_in_failed(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    db_session: Session,
    samples: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    invoice_id = add_invoice(session_factory, storage, samples["cii_xrechnung"], SourceType.XML)

    def explode(content: bytes, source_type: SourceType) -> None:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(processing, "invoice_xml", explode)

    process_invoice(session_factory, storage, NO_VALIDATOR, None, invoice_id)

    invoice = load(db_session, invoice_id)
    assert invoice.status is InvoiceStatus.FAILED
    assert invoice.status_reason == processing.INTERNAL_ERROR_REASON
    # The details go to the logs, not to the user-facing reason.
    assert "disk on fire" in caplog.text
    assert fields(db_session, invoice_id) == {}


def test_recovery_resumes_received_and_interrupted_invoices(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    db_session: Session,
    samples: dict[str, bytes],
) -> None:
    interrupted = add_invoice(
        session_factory, storage, samples["cii_xrechnung"], SourceType.XML, InvoiceStatus.PROCESSING
    )
    waiting = add_invoice(session_factory, storage, samples["ubl_xrechnung"], SourceType.XML)
    done = add_invoice(
        session_factory, storage, samples["plain_pdf"], SourceType.PDF, InvoiceStatus.FAILED
    )

    recover_unfinished(session_factory, storage, NO_VALIDATOR, None)

    assert load(db_session, interrupted).status is InvoiceStatus.READY
    assert status_changes(db_session, interrupted) == [
        ("processing", "received"),
        ("received", "processing"),
        ("processing", "ready"),
    ]
    assert load(db_session, waiting).status is InvoiceStatus.READY
    assert load(db_session, done).status is InvoiceStatus.FAILED
    assert status_changes(db_session, done) == []


def test_app_startup_resumes_unfinished_invoices(
    settings: Settings,
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    db_session: Session,
    samples: dict[str, bytes],
) -> None:
    invoice_id = add_invoice(
        session_factory, storage, samples["ubl_xrechnung"], SourceType.XML, InvoiceStatus.PROCESSING
    )

    # Leaving the context waits for the startup recovery to finish.
    with TestClient(create_app(settings)):
        pass

    assert load(db_session, invoice_id).status is InvoiceStatus.READY


def test_app_starts_even_if_recovery_fails(
    settings: Settings,
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def broken(*_: object) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(main, "recover_unfinished", broken)

    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200

    # create_app configures JSON logging to stdout, which replaces pytest's log capture.
    assert "Could not resume unfinished invoices" in capsys.readouterr().out


# --- Atomic claim: one invoice is processed once, even by two workers at the same moment -------


class SlowValidator(KositValidator):
    """Counts validations and takes a while, so the winner is still busy when the loser claims."""

    def __init__(self) -> None:
        super().__init__(None, 1.0)
        self.calls = 0
        self._lock = threading.Lock()

    def validate(self, xml: bytes) -> Validation:
        with self._lock:
            self.calls += 1
        time.sleep(0.2)
        return super().validate(xml)


def _check_types(db_session: Session, invoice_id: uuid.UUID) -> Counter[str]:
    rows = db_session.scalars(select(Check.type).where(Check.invoice_id == invoice_id))
    return Counter(rows)


def test_claim_waits_for_a_concurrent_claim_and_then_skips(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    engine: Engine,
    db_session: Session,
    samples: dict[str, bytes],
) -> None:
    """The claim is one conditional UPDATE. PostgreSQL locks the row for the first one; a second
    UPDATE waits for that lock, re-reads the row after the commit (READ COMMITTED), finds it no
    longer `received` and matches nothing. Here the first claim is held open on purpose."""
    invoice_id = add_invoice(session_factory, storage, samples["ubl_xrechnung"], SourceType.XML)
    validator = SlowValidator()

    with engine.connect() as other_worker:
        transaction = other_worker.begin()
        claimed = other_worker.execute(
            update(Invoice)
            .where(Invoice.id == invoice_id, Invoice.status == InvoiceStatus.RECEIVED)
            .values(status=InvoiceStatus.PROCESSING)
        )
        assert claimed.rowcount == 1

        worker = threading.Thread(
            target=process_invoice, args=(session_factory, storage, validator, None, invoice_id)
        )
        worker.start()
        worker.join(timeout=0.5)
        assert worker.is_alive(), "the second claim must wait for the first one's row lock"

        transaction.commit()
        worker.join(timeout=10)
        assert not worker.is_alive()

    # The waiting worker matched no row: it did no work and wrote nothing.
    assert validator.calls == 0
    assert status_changes(db_session, invoice_id) == []
    assert fields(db_session, invoice_id) == {}
    assert _check_types(db_session, invoice_id) == Counter()
    assert load(db_session, invoice_id).status is InvoiceStatus.PROCESSING


@pytest.mark.usefixtures("seeded")
@pytest.mark.parametrize("attempt", range(5))
def test_two_simultaneous_runs_process_the_invoice_once(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    db_session: Session,
    samples: dict[str, bytes],
    attempt: int,
) -> None:
    """Startup recovery and the upload's own task picking up the same invoice at once."""
    invoice_id = add_invoice(session_factory, storage, samples["ubl_xrechnung"], SourceType.XML)
    validator = SlowValidator()
    start = threading.Barrier(2)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            start.wait(timeout=5)
            process_invoice(session_factory, storage, validator, None, invoice_id)
        except BaseException as error:
            errors.append(error)

    workers = [threading.Thread(target=run) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=10)

    assert errors == []
    assert validator.calls == 1
    assert load(db_session, invoice_id).status is InvoiceStatus.READY
    assert status_changes(db_session, invoice_id) == [
        ("received", "processing"),
        ("processing", "ready"),
    ]
    assert _check_types(db_session, invoice_id) == Counter(
        ["kosit", "vat_math", "duplicate", "supplier_known", "iban", "po_match"]
    )
    rows = db_session.scalars(select(InvoiceField).where(InvoiceField.invoice_id == invoice_id))
    assert len(rows.all()) == len(fields(db_session, invoice_id))
