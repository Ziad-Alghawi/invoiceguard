"""Demo reset (ADR-014): empties invoices, exports and files, keeps the audit log, and loads the
sample invoices with the same outcome every time."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from invoiceguard_api import demo
from invoiceguard_api.checks import KositValidator
from invoiceguard_api.db import make_session_factory
from invoiceguard_api.models import (
    AuditEvent,
    Booking,
    DatevExport,
    Embedding,
    Invoice,
    RulebookChunk,
    SecurityEvent,
    Supplier,
    User,
)
from invoiceguard_api.rulebook.chunks import load
from invoiceguard_api.settings import Settings, get_settings
from invoiceguard_api.storage import FileStorage

RULEBOOK = Path(__file__).resolve().parents[3] / "docs" / "rulebook"

# What a visitor sees after a reset (without the KoSIT validator and without an LLM key).
EXPECTED = {
    "01_it_service_clean.xml": ("ready", None),
    "02_it_service_changed_iban.xml": ("blocked", "Failed checks: iban."),
    "03_logistik_over_po.xml": ("blocked", "Failed checks: po_match."),
    "04_buerobedarf_cii.xml": ("ready", None),
    "05_unknown_supplier_zugferd.xml": ("ready", None),
    # A note that tries to instruct an AI (R2-4); every other check passes.
    "06_it_service_injected_note.xml": ("blocked", "Failed checks: prompt_injection."),
}


def _reset(engine: Engine, settings: Settings) -> None:
    demo.reset_demo(
        make_session_factory(engine),
        FileStorage(settings.storage_dir),
        KositValidator(None, 1.0),
        None,
        settings.embedding_model,
        RULEBOOK,
    )


def _outcomes(session: Session) -> dict[str, tuple[str, str | None]]:
    invoices = session.scalars(select(Invoice)).all()
    return {i.original_filename: (i.status.value, i.status_reason) for i in invoices}


def test_samples_are_packaged_in_loading_order() -> None:
    assert [name for name, _ in demo.sample_invoices()] == list(EXPECTED)


def test_reset_loads_the_samples_with_their_outcomes(
    engine: Engine, settings: Settings, db_session: Session
) -> None:
    _reset(engine, settings)

    assert _outcomes(db_session) == EXPECTED
    assert db_session.scalar(select(func.count(Supplier.id))) == 5
    # The booking history with its vectors (ADR-020), again after a second reset, not twice.
    _reset(engine, settings)
    assert db_session.scalar(select(func.count(Booking.id))) == 159
    assert db_session.scalar(select(func.count(Embedding.id))) == 59
    # The rulebook's sections (R3-4b), with their packaged vectors.
    chunks = db_session.scalars(select(RulebookChunk)).all()
    assert len(chunks) == len(load(RULEBOOK))
    assert all(chunk.vector is not None for chunk in chunks)


def test_reset_deletes_invoices_exports_and_files_and_keeps_the_audit_log(
    engine: Engine, settings: Settings, db_session: Session, reviewer: User
) -> None:
    _reset(engine, settings)
    old = db_session.scalars(select(Invoice)).all()
    old_paths = [settings.storage_dir / invoice.storage_path for invoice in old]
    old_ids = {invoice.id for invoice in old}
    export = DatevExport(
        user_id=reviewer.id,
        invoice_count=1,
        fiscal_year_start=date(2026, 1, 1),
        date_from=date(2026, 11, 5),
        date_to=date(2026, 11, 5),
        filename="EXTF_Buchungsstapel_demo.csv",
        content=b"EXTF",
    )
    db_session.add(export)
    db_session.flush()
    old[0].datev_export_id = export.id
    db_session.commit()
    audit_before = db_session.scalar(select(func.count(AuditEvent.id))) or 0

    _reset(engine, settings)
    db_session.expire_all()

    new = db_session.scalars(select(Invoice)).all()
    assert {invoice.id for invoice in new}.isdisjoint(old_ids)
    assert _outcomes(db_session) == EXPECTED
    assert db_session.scalar(select(func.count(DatevExport.id))) == 0
    # Same content, same content-addressed path: the files are there again after the reload.
    assert all(path.exists() for path in old_paths)
    assert (db_session.scalar(select(func.count(AuditEvent.id))) or 0) > audit_before
    [reset_event] = db_session.scalars(
        select(AuditEvent).where(AuditEvent.action == "demo.reset").order_by(AuditEvent.id)
    ).all()[-1:]
    assert reset_event.details == {"deleted_invoices": 6, "deleted_exports": 1}
    # The security log is append-only too: the first load's injection event stays, the reload
    # adds one for the new invoice.
    injections = db_session.scalars(
        select(SecurityEvent).where(SecurityEvent.type == "injection_suspected")
    ).all()
    assert len(injections) == 2
    assert injections[0].invoice_id in old_ids


def test_storage_delete_ignores_a_missing_file(tmp_path: Path) -> None:
    storage = FileStorage(tmp_path)
    path = storage.save("ab" * 32, "xml", b"<x/>")

    storage.delete(path)
    storage.delete(path)

    assert not (tmp_path / path).exists()


def test_main_refuses_without_demo_mode(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", database_url)
    monkeypatch.delenv("INVOICEGUARD_DEMO_MODE", raising=False)
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit, match="Refusing to reset"):
            demo.main()
    finally:
        get_settings.cache_clear()


def test_main_refuses_to_run_as_the_app_role(
    app_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Owner tasks run as the owner (ADR-022), never through the api's role."""
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", app_database_url)
    monkeypatch.setenv("INVOICEGUARD_DEMO_MODE", "true")
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit, match="Refusing to reset as invoiceguard_app"):
            demo.main()
    finally:
        get_settings.cache_clear()


def test_main_resets_the_configured_database(
    engine: Engine, database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", database_url)
    monkeypatch.setenv("INVOICEGUARD_DEMO_MODE", "true")
    monkeypatch.setenv("INVOICEGUARD_STORAGE_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("INVOICEGUARD_VALIDATOR_URL", raising=False)
    monkeypatch.delenv("INVOICEGUARD_LLM_API_KEY", raising=False)
    get_settings.cache_clear()
    try:
        demo.main()
    finally:
        get_settings.cache_clear()

    with Session(engine) as session:
        assert _outcomes(session) == EXPECTED
