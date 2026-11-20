"""Reset the public demo (ADR-014): delete every invoice, export, stored file and graph thread,
restore the master data and the booking history with its packaged vectors (ADR-020), sync the
rulebook (R3-4b), and process the sample invoices again, so each visitor finds the same queue.

Deletes data, so it runs only with INVOICEGUARD_DEMO_MODE=true, and only as the database owner
(ADR-022): on the demo a Kubernetes CronJob runs it as the owner every night (docs/deploy.md),
locally `make demo-reset` runs it in a one-off `migrate` container; it refuses to run as the api's
restricted role. The audit log is append-only and is kept; the reset itself is an
audit event. LLM costs stay in `model_calls` (the invoice link is
set to null), so a reset does not refill the daily budget.

Run with `make demo-reset` locally, or `uv run invoiceguard-demo-reset` with the owner's database
URL.
"""

import logging
import sys
import uuid
from importlib.resources import files
from pathlib import Path

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session, sessionmaker

from invoiceguard_api.booking.history import import_packaged
from invoiceguard_api.checks import KositValidator
from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.db_roles import APP_ROLE
from invoiceguard_api.extraction import PdfExtractor
from invoiceguard_api.filetype import source_type_for
from invoiceguard_api.invoices import add_received
from invoiceguard_api.logging import configure_logging
from invoiceguard_api.main import make_extractor
from invoiceguard_api.models import AuditEvent, DatevExport, Invoice
from invoiceguard_api.processing import delete_threads, process_invoice
from invoiceguard_api.rulebook import chunks as rulebook_chunks
from invoiceguard_api.rulebook import index as rulebook_index
from invoiceguard_api.seed import seed_demo_data
from invoiceguard_api.settings import get_settings
from invoiceguard_api.storage import FileStorage

logger = logging.getLogger(__name__)

DEMO_ACTOR = "demo-reset"
SAMPLES = files("invoiceguard_api") / "demo_invoices"


def sample_invoices() -> list[tuple[str, bytes]]:
    """The demo sample files (name, content), in the order they are loaded."""
    samples = [entry for entry in SAMPLES.iterdir() if entry.name.endswith((".xml", ".pdf"))]
    return [(entry.name, entry.read_bytes()) for entry in sorted(samples, key=lambda e: e.name)]


def _clear(
    session_factory: sessionmaker[Session],
    session: Session,
    storage: FileStorage,
    embedding_model: str,
    rulebook_dir: Path | None,
) -> tuple[int, int]:
    """Delete invoices (fields, checks and bookings cascade) and exports, then their files and
    threads; restore the master data and the booking history."""
    rows = session.execute(select(Invoice.id, Invoice.storage_path)).all()
    paths = [row.storage_path for row in rows]
    exports = session.scalar(select(func.count(DatevExport.id))) or 0
    # Invoices first: they point at the export that contains them.
    session.execute(delete(Invoice))
    session.execute(delete(DatevExport))
    session.add(
        AuditEvent(
            actor=DEMO_ACTOR,
            action="demo.reset",
            entity_type="demo",
            entity_id="demo",
            details={"deleted_invoices": len(paths), "deleted_exports": exports},
        )
    )
    seed_demo_data(session)
    import_packaged(session, embedding_model)
    session.commit()
    if rulebook_dir is not None:
        # No key on the demo: the packaged vectors only.
        rulebook_index.sync(session, rulebook_chunks.load(rulebook_dir), embedding_model, None)
    for path in paths:
        storage.delete(path)
    delete_threads(session_factory, [row.id for row in rows])
    return len(paths), exports


def reset_demo(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    validator: KositValidator,
    extractor: PdfExtractor | None,
    embedding_model: str,
    rulebook_dir: Path | None = None,
) -> list[uuid.UUID]:
    """Empty the demo and load the samples; returns the new invoice IDs in loading order.

    The samples are processed here, one after another, not by the API's background tasks.
    """
    with session_factory() as session:
        invoices, exports = _clear(session_factory, session, storage, embedding_model, rulebook_dir)
        logger.info("Deleted %d invoices and %d DATEV exports", invoices, exports)
        ids = []
        for name, content in sample_invoices():
            source_type = source_type_for(name, content)
            if source_type is None:
                raise ValueError(f"Demo sample {name} is not an XML or PDF invoice")
            invoice = add_received(session, storage, name, source_type, content, actor=DEMO_ACTOR)
            session.commit()
            ids.append(invoice.id)
    for invoice_id in ids:
        process_invoice(session_factory, storage, validator, extractor, invoice_id)
    return ids


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.demo_mode:
        sys.exit(
            "Refusing to reset: this deletes every invoice. Set INVOICEGUARD_DEMO_MODE=true on "
            "the demo server only."
        )
    engine = make_engine(str(settings.database_url))
    try:
        with engine.connect() as connection:
            if connection.execute(text("SELECT current_user")).scalar_one() == APP_ROLE:
                sys.exit(
                    f"Refusing to reset as {APP_ROLE}: owner tasks run as the database owner. "
                    "Use `make demo-reset` locally, the demo-reset CronJob on the demo."
                )
        ids = reset_demo(
            make_session_factory(engine),
            FileStorage(settings.storage_dir),
            KositValidator(
                None if settings.validator_url is None else str(settings.validator_url),
                settings.validator_timeout_seconds,
            ),
            make_extractor(settings, None),
            settings.embedding_model,
            settings.rulebook_dir,
        )
    finally:
        engine.dispose()
    logger.info("Demo reset: loaded %d sample invoices", len(ids))
