"""Background processing of uploaded invoices (ADR-007): received → processing → final status.

Steps: read the XML, validate it with KoSIT (ADR-009), store the fields, run the checks; any
failed check ends in `blocked`, otherwise `ready`. A PDF without XML moves to
`awaiting_extraction`; when an LLM is configured, the same task then claims it again and
extracts the fields (ADR-010): awaiting_extraction → processing → checks → final status.

Plain sync functions: FastAPI runs them in its thread pool (ADR-008). Every step is safe to run
twice: claiming is a conditional update, and fields and check results are replaced in the same
transaction that sets the final status. Each status change writes an audit event.
"""

import logging
import uuid
from decimal import Decimal
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
from invoiceguard_api.checks.model import Validation
from invoiceguard_api.extraction import Extraction, PdfExtractor
from invoiceguard_api.models import (
    AuditEvent,
    FieldSource,
    Invoice,
    InvoiceField,
    InvoiceStatus,
    ModelCall,
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
EXTRACTION_OFF_REASON = (
    "The PDF has no embedded e-invoice XML, and LLM extraction is skipped: no API key is "
    "configured (INVOICEGUARD_LLM_API_KEY)."
)
INTERNAL_ERROR_REASON = "Processing failed with an internal error; see the API logs."
RESTART_REASON = "Reset after an API restart interrupted processing."
EXTRACTION_PURPOSE = "extraction"
NO_XML = Validation(
    outcome="not_applicable",
    reason="No e-invoice XML to validate: the fields were extracted from the PDF by an LLM.",
)


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


def _claim(session: Session, invoice_id: uuid.UUID, waiting: InvoiceStatus) -> Invoice | None:
    """Move an invoice from `waiting` to `processing`; None if another run has it or it is done."""
    claimed = session.execute(
        update(Invoice)
        .where(Invoice.id == invoice_id, Invoice.status == waiting)
        .values(status=InvoiceStatus.PROCESSING, status_reason=None)
        .returning(Invoice.id)
    ).scalar_one_or_none()
    if claimed is None:
        session.rollback()
        return None
    session.add(_status_event(invoice_id, waiting, InvoiceStatus.PROCESSING, None))
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


def _xml_fields(invoice_id: uuid.UUID, parsed: ParsedInvoice) -> list[InvoiceField]:
    return [
        InvoiceField(
            invoice_id=invoice_id,
            code=row.code,
            line_no=row.line_no,
            value=row.value,
            source=FieldSource.XML,
        )
        for row in to_field_rows(parsed)
    ]


def _llm_fields(invoice_id: uuid.UUID, extraction: Extraction) -> list[InvoiceField]:
    """Each row with its confidence and evidence; line terms share their line's (ADR-010)."""
    terms = {field.code: field for field in extraction.confidences if field.code is not None}
    lines = {field.line_no: field for field in extraction.confidences if field.line_no is not None}
    rows = []
    for row in to_field_rows(extraction.invoice):
        field = terms[row.code] if row.line_no is None else lines[row.line_no]
        rows.append(
            InvoiceField(
                invoice_id=invoice_id,
                code=row.code,
                line_no=row.line_no,
                value=row.value,
                source=FieldSource.LLM,
                confidence=field.confidence,
                evidence=field.evidence,
            )
        )
    return rows


def _check_and_finish(
    session: Session,
    invoice: Invoice,
    parsed: ParsedInvoice,
    validation: Validation,
    fields: list[InvoiceField],
    extracted: Extraction | None = None,
    confidence_threshold: Decimal = Decimal(1),
    **extra: Any,
) -> None:
    """Replace the fields and check results and set the final status, in one transaction."""
    session.execute(delete(InvoiceField).where(InvoiceField.invoice_id == invoice.id))
    session.add_all(fields)
    context = load_context(session, invoice.id, parsed, validation, extracted, confidence_threshold)
    results = run_checks(context)
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
        **extra,
    )


def _run(
    session: Session,
    storage: FileStorage,
    validator: KositValidator,
    extractor: PdfExtractor | None,
    invoice: Invoice,
) -> None:
    try:
        xml = invoice_xml(storage.read(invoice.storage_path), invoice.source_type)
        parsed = read_invoice_xml(xml)
    except NoEmbeddedXml:
        reason = EXTRACTION_OFF_REASON if extractor is None else AWAITING_EXTRACTION_REASON
        _finish(session, invoice, InvoiceStatus.AWAITING_EXTRACTION, reason)
        return
    except ParseError as error:
        _finish(session, invoice, InvoiceStatus.FAILED, str(error))
        return
    # Before any write, so the call (up to the validator timeout) holds no row locks.
    validation = validator.validate(xml)
    _check_and_finish(session, invoice, parsed, validation, _xml_fields(invoice.id, parsed))


def _extract(
    session: Session, storage: FileStorage, extractor: PdfExtractor, invoice: Invoice
) -> None:
    # The claim is committed, so the model calls (seconds each) hold no row locks.
    result = extractor.extract(storage.read(invoice.storage_path))
    session.add_all(
        ModelCall(
            invoice_id=invoice.id,
            at=call.at,
            purpose=EXTRACTION_PURPOSE,
            model=call.model,
            status=call.status,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cost_usd=call.cost_usd,
            latency_ms=call.latency_ms,
            error=call.error,
        )
        for call in result.calls
    )
    # Committed on its own: the cost stays logged even if a later step fails.
    session.commit()
    summary = {
        "model": extractor.model,
        "calls": len(result.calls),
        "cost_usd": str(sum((call.cost_usd or Decimal(0) for call in result.calls), Decimal(0))),
    }
    if result.extraction is None:
        _finish(session, invoice, InvoiceStatus.FAILED, result.failure, extraction=summary)
        return
    _check_and_finish(
        session,
        invoice,
        result.extraction.invoice,
        NO_XML,
        _llm_fields(invoice.id, result.extraction),
        result.extraction,
        extractor.confidence_threshold,
        extraction=summary,
    )


def process_invoice(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    validator: KositValidator,
    extractor: PdfExtractor | None,
    invoice_id: uuid.UUID,
) -> None:
    """Parse and check one invoice; any error in the work ends in status `failed`.

    A plain PDF goes on to `extract_invoice` when an extractor is configured. If the database
    itself fails, the invoice stays `processing` and startup recovery resumes it.
    """
    with session_factory() as session:
        invoice = _claim(session, invoice_id, InvoiceStatus.RECEIVED)
        if invoice is None:
            logger.info("Invoice %s is not waiting for processing; skipped", invoice_id)
            return
        try:
            _run(session, storage, validator, extractor, invoice)
        except Exception:
            logger.exception("Processing invoice %s failed", invoice_id)
            session.rollback()
            _finish(session, invoice, InvoiceStatus.FAILED, INTERNAL_ERROR_REASON)
        awaiting = invoice.status is InvoiceStatus.AWAITING_EXTRACTION
    if awaiting and extractor is not None:
        extract_invoice(session_factory, storage, extractor, invoice_id)


def extract_invoice(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    extractor: PdfExtractor,
    invoice_id: uuid.UUID,
) -> None:
    """Extract and check an invoice in `awaiting_extraction`; any error ends in `failed`."""
    with session_factory() as session:
        invoice = _claim(session, invoice_id, InvoiceStatus.AWAITING_EXTRACTION)
        if invoice is None:
            logger.info("Invoice %s is not waiting for extraction; skipped", invoice_id)
            return
        try:
            _extract(session, storage, extractor, invoice)
        except Exception:
            logger.exception("Extracting invoice %s failed", invoice_id)
            session.rollback()
            _finish(session, invoice, InvoiceStatus.FAILED, INTERNAL_ERROR_REASON)


def _waiting(session: Session, status: InvoiceStatus) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(Invoice.id)
            .where(Invoice.status == status)
            .order_by(Invoice.created_at, Invoice.id)
        ).all()
    )


def recover_unfinished(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    validator: KositValidator,
    extractor: PdfExtractor | None,
) -> None:
    """On startup: reset invoices a restart left in `processing`, then process all `received`
    and, when an extractor is configured, extract all `awaiting_extraction`.

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
        pending = _waiting(session, InvoiceStatus.RECEIVED)
        # Read before processing `received`: those go on to extraction by themselves.
        awaiting = [] if extractor is None else _waiting(session, InvoiceStatus.AWAITING_EXTRACTION)
    if pending or awaiting:
        logger.info(
            "Resuming %d unfinished and %d awaiting-extraction invoice(s) after startup",
            len(pending),
            len(awaiting),
        )
    for invoice_id in pending:
        process_invoice(session_factory, storage, validator, extractor, invoice_id)
    if extractor is not None:
        for invoice_id in awaiting:
            extract_invoice(session_factory, storage, extractor, invoice_id)
