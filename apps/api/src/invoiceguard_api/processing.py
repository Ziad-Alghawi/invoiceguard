"""Background processing of uploaded invoices (ADR-007): received → processing → final status.

Steps: read the XML, validate it with KoSIT (ADR-009), store the fields, run the checks; any
failed check ends in `blocked`, otherwise `ready`. A PDF without XML waits for extraction.

Plain sync functions: FastAPI runs them in its thread pool (ADR-008). Every step is safe to run
twice: claiming is a conditional update, and fields and check results are replaced in the same
transaction that sets the final status. Each status change writes an audit event.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from invoiceguard_api.checks import (
    KositValidator,
    final_status,
    load_context,
    replace_results,
    run_checks,
    summarise,
)
from invoiceguard_api.models import (
    AuditEvent,
    FieldSource,
    Invoice,
    InvoiceField,
    InvoiceStatus,
)
from invoiceguard_api.parsing import (
    NoEmbeddedXml,
    ParsedInvoice,
    ParseError,
    invoice_xml,
    read_invoice_xml,
)
from invoiceguard_api.parsing.fields import to_field_rows
from invoiceguard_api.storage import FileStorage

logger = logging.getLogger(__name__)

SYSTEM_ACTOR = "system"
AWAITING_EXTRACTION_REASON = "The PDF has no embedded e-invoice XML; it needs LLM extraction."
INTERNAL_ERROR_REASON = "Processing failed with an internal error; see the API logs."
RESTART_REASON = "Reset after an API restart interrupted processing."


def _status_event(
    invoice_id: uuid.UUID,
    old: InvoiceStatus,
    new: InvoiceStatus,
    reason: str | None,
    **extra: Any,
) -> AuditEvent:
    return AuditEvent(
        actor=SYSTEM_ACTOR,
        action="invoice.status_changed",
        entity_type="invoice",
        entity_id=str(invoice_id),
        details={"from": old.value, "to": new.value, "reason": reason, **extra},
    )


def _claim(session: Session, invoice_id: uuid.UUID) -> Invoice | None:
    """Move a `received` invoice to `processing`; None if another run has it or it is done."""
    claimed = session.execute(
        update(Invoice)
        .where(Invoice.id == invoice_id, Invoice.status == InvoiceStatus.RECEIVED)
        .values(status=InvoiceStatus.PROCESSING, status_reason=None)
        .returning(Invoice.id)
    ).scalar_one_or_none()
    if claimed is None:
        session.rollback()
        return None
    session.add(_status_event(invoice_id, InvoiceStatus.RECEIVED, InvoiceStatus.PROCESSING, None))
    session.commit()
    return session.get(Invoice, invoice_id, populate_existing=True)


def _finish(
    session: Session,
    invoice: Invoice,
    status: InvoiceStatus,
    reason: str | None,
    **extra: Any,
) -> None:
    session.add(_status_event(invoice.id, invoice.status, status, reason, **extra))
    invoice.status = status
    invoice.status_reason = reason
    session.commit()
    logger.info("Invoice %s is %s", invoice.id, status.value)


def _replace_fields(session: Session, invoice_id: uuid.UUID, parsed: ParsedInvoice) -> None:
    session.execute(
        delete(InvoiceField).where(
            InvoiceField.invoice_id == invoice_id, InvoiceField.source == FieldSource.XML
        )
    )
    session.add_all(
        InvoiceField(
            invoice_id=invoice_id,
            code=row.code,
            line_no=row.line_no,
            value=row.value,
            source=FieldSource.XML,
        )
        for row in to_field_rows(parsed)
    )


def _run(
    session: Session, storage: FileStorage, validator: KositValidator, invoice: Invoice
) -> None:
    try:
        xml = invoice_xml(storage.read(invoice.storage_path), invoice.source_type)
        parsed = read_invoice_xml(xml)
    except NoEmbeddedXml:
        _finish(session, invoice, InvoiceStatus.AWAITING_EXTRACTION, AWAITING_EXTRACTION_REASON)
        return
    except ParseError as error:
        _finish(session, invoice, InvoiceStatus.FAILED, str(error))
        return
    # Before any write, so the call (up to the validator timeout) holds no row locks.
    validation = validator.validate(xml)
    _replace_fields(session, invoice.id, parsed)
    results = run_checks(load_context(session, invoice.id, parsed, validation))
    replace_results(session, invoice.id, results)
    summary = summarise(results)
    status = final_status(results)
    reason = (
        None
        if status is InvoiceStatus.READY
        else "Failed checks: " + ", ".join(summary["failed_checks"]) + "."
    )
    _finish(
        session,
        invoice,
        status,
        reason,
        syntax=parsed.syntax,
        warnings=list(parsed.warnings),
        checks=summary,
    )


def process_invoice(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    validator: KositValidator,
    invoice_id: uuid.UUID,
) -> None:
    """Parse and check one invoice; any error in the work ends in status `failed`.

    If the database itself fails, the invoice stays `processing` and startup recovery resumes it.
    """
    with session_factory() as session:
        invoice = _claim(session, invoice_id)
        if invoice is None:
            logger.info("Invoice %s is not waiting for processing; skipped", invoice_id)
            return
        try:
            _run(session, storage, validator, invoice)
        except Exception:
            logger.exception("Processing invoice %s failed", invoice_id)
            session.rollback()
            _finish(session, invoice, InvoiceStatus.FAILED, INTERNAL_ERROR_REASON)


def recover_unfinished(
    session_factory: sessionmaker[Session], storage: FileStorage, validator: KositValidator
) -> None:
    """On startup: reset invoices a restart left in `processing`, then process all `received`.

    Assumes one API process (ADR-007); with several, this would take over another's work.
    """
    with session_factory() as session:
        stuck = session.scalars(
            select(Invoice).where(Invoice.status == InvoiceStatus.PROCESSING)
        ).all()
        for invoice in stuck:
            session.add(
                _status_event(
                    invoice.id, InvoiceStatus.PROCESSING, InvoiceStatus.RECEIVED, RESTART_REASON
                )
            )
            invoice.status = InvoiceStatus.RECEIVED
            invoice.status_reason = RESTART_REASON
        session.commit()
        pending = session.scalars(
            select(Invoice.id)
            .where(Invoice.status == InvoiceStatus.RECEIVED)
            .order_by(Invoice.created_at, Invoice.id)
        ).all()
    if pending:
        logger.info("Resuming %d unfinished invoice(s) after startup", len(pending))
    for invoice_id in pending:
        process_invoice(session_factory, storage, validator, invoice_id)
