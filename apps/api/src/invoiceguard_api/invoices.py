"""Invoice upload, list, detail and the original file. Upload schedules background processing
(ADR-007). Every endpoint needs a logged-in user (ADR-011).
"""

import hashlib
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, BinaryIO
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from invoiceguard_api.auth import CurrentUser, current_user
from invoiceguard_api.db import DbSession
from invoiceguard_api.filetype import safe_filename, source_type_for
from invoiceguard_api.models import (
    AuditEvent,
    Check,
    CheckStatus,
    FieldSource,
    Invoice,
    InvoiceField,
    InvoiceStatus,
    ModelCall,
    SourceType,
)
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS, LINE_TERMS
from invoiceguard_api.processing import process_invoice
from invoiceguard_api.storage import FileStorage

router = APIRouter(prefix="/invoices", tags=["invoices"], dependencies=[Depends(current_user)])

CHUNK_BYTES = 64 * 1024
# The field name for each EN 16931 term code, for example BT-84 -> payee_iban.
TERM_NAMES = {code: name for name, code in (DOCUMENT_TERMS | LINE_TERMS).items()}
MEDIA_TYPES = {SourceType.XML: "application/xml", SourceType.PDF: "application/pdf"}


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: InvoiceStatus
    status_reason: str | None
    source_type: SourceType
    original_filename: str
    sha256: str
    size_bytes: int
    created_at: datetime


class CheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: str
    status: CheckStatus
    message: str
    evidence: dict[str, Any]
    created_at: datetime


class FieldOut(BaseModel):
    code: str
    # The term's name, for example payee_iban for BT-84.
    name: str
    # Null for document-level terms; the 1-based line number for line terms.
    line_no: int | None
    value: str
    source: FieldSource
    # Null for values read from XML; 0..1 for LLM extraction.
    confidence: Decimal | None
    # An LLM confidence below the threshold: the reviewer must compare the value with the PDF.
    low_confidence: bool
    # LLM extraction only: where the value is printed, {"page": 1, "snippet": "..."}.
    evidence: dict[str, Any] | None


class InvoiceDetailOut(InvoiceOut):
    # Document terms first (by code), then the lines in order.
    fields: list[FieldOut]
    # Worst first: failed, warning, skipped, passed.
    checks: list[CheckOut]
    # Download path of the uploaded file, relative to the API root.
    file_url: str
    # LLM calls made for this invoice and their total cost in US dollars (ADR-004). A call
    # without a known price adds nothing here; it fails the invoice instead.
    llm_calls: int
    llm_cost_usd: Decimal


# The order a reviewer reads check results in.
SEVERITY_ORDER = (CheckStatus.FAILED, CheckStatus.WARNING, CheckStatus.SKIPPED, CheckStatus.PASSED)


class ErrorOut(BaseModel):
    detail: str


class DuplicateDetail(BaseModel):
    message: str
    invoice_id: uuid.UUID


class DuplicateOut(BaseModel):
    detail: DuplicateDetail


def _read_limited(file: BinaryIO, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := file.read(CHUNK_BYTES):
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE, f"File is larger than {max_bytes} bytes."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _duplicate(invoice_id: uuid.UUID) -> HTTPException:
    detail = DuplicateDetail(message="This file was already uploaded.", invoice_id=invoice_id)
    return HTTPException(status.HTTP_409_CONFLICT, detail.model_dump(mode="json"))


def _find_by_sha256(session: Session, sha256: str) -> uuid.UUID | None:
    return session.scalar(select(Invoice.id).where(Invoice.sha256 == sha256))


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_409_CONFLICT: {"model": DuplicateOut, "description": "Same file uploaded"},
        status.HTTP_413_CONTENT_TOO_LARGE: {"model": ErrorOut, "description": "File too large"},
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {"model": ErrorOut, "description": "Not XML/PDF"},
    },
)
def upload_invoice(
    file: UploadFile,
    session: DbSession,
    user: CurrentUser,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
) -> InvoiceOut:
    """Store an XRechnung/ZUGFeRD XML or PDF file with status `received` and process it later.

    Poll `GET /invoices/{id}` (the Location header) until the status is no longer `received` or
    `processing`.
    """
    content = _read_limited(file.file, request.app.state.settings.max_upload_bytes)
    filename = safe_filename(file.filename or "")
    source_type = source_type_for(filename, content)
    if source_type is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "Upload an XML or PDF invoice; the file extension must match its content.",
        )

    sha256 = hashlib.sha256(content).hexdigest()
    if (existing_id := _find_by_sha256(session, sha256)) is not None:
        raise _duplicate(existing_id)

    storage: FileStorage = request.app.state.storage
    invoice = Invoice(
        id=uuid.uuid4(),
        status=InvoiceStatus.RECEIVED,
        source_type=source_type,
        original_filename=filename,
        sha256=sha256,
        size_bytes=len(content),
        storage_path=storage.save(sha256, source_type.value, content),
    )
    details: dict[str, Any] = {
        "filename": filename,
        "sha256": sha256,
        "size_bytes": len(content),
        "source_type": source_type.value,
    }
    session.add(invoice)
    session.add(
        AuditEvent(
            actor=user.email,
            user_id=user.id,
            action="invoice.received",
            entity_type="invoice",
            entity_id=str(invoice.id),
            details=details,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        # A parallel upload of the same file won the race to the unique sha256 index.
        session.rollback()
        if (existing_id := _find_by_sha256(session, sha256)) is None:
            raise
        raise _duplicate(existing_id) from None

    session.refresh(invoice)
    background_tasks.add_task(
        process_invoice,
        request.app.state.session_factory,
        storage,
        request.app.state.validator,
        request.app.state.extractor,
        invoice.id,
    )
    response.headers["Location"] = str(request.url_for("get_invoice", invoice_id=invoice.id))
    return InvoiceOut.model_validate(invoice)


@router.get("")
def list_invoices(
    session: DbSession,
    response: Response,
    status_filter: Annotated[list[InvoiceStatus] | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[InvoiceOut]:
    """Invoices, newest first. Repeat `status` to filter on several statuses.

    The `X-Total-Count` header holds the number of matching invoices, for paging.
    """
    query = select(Invoice)
    if status_filter:
        query = query.where(Invoice.status.in_(status_filter))
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    response.headers["X-Total-Count"] = str(total)
    invoices = session.scalars(
        query.order_by(Invoice.created_at.desc(), Invoice.id.desc()).limit(limit).offset(offset)
    )
    return [InvoiceOut.model_validate(invoice) for invoice in invoices]


def get_invoice_or_404(session: Session, invoice_id: uuid.UUID) -> Invoice:
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")
    return invoice


def _field_out(field: InvoiceField, threshold: Decimal) -> FieldOut:
    return FieldOut(
        code=field.code,
        name=TERM_NAMES.get(field.code, field.code),
        line_no=field.line_no,
        value=field.value,
        source=field.source,
        confidence=field.confidence,
        low_confidence=field.confidence is not None and field.confidence < threshold,
        evidence=field.evidence,
    )


@router.get(
    "/{invoice_id}",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Unknown invoice"}},
)
def get_invoice(invoice_id: uuid.UUID, session: DbSession, request: Request) -> InvoiceDetailOut:
    """The invoice with its fields and check results (empty until processing has run)."""
    invoice = get_invoice_or_404(session, invoice_id)
    threshold = request.app.state.settings.extraction_confidence_threshold
    fields = session.scalars(
        select(InvoiceField)
        .where(InvoiceField.invoice_id == invoice_id)
        .order_by(InvoiceField.line_no.asc().nulls_first(), InvoiceField.code)
    ).all()
    checks = session.scalars(select(Check).where(Check.invoice_id == invoice_id)).all()
    ordered = sorted(checks, key=lambda check: (SEVERITY_ORDER.index(check.status), check.type))
    calls, cost = session.execute(
        select(func.count(ModelCall.id), func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(
            ModelCall.invoice_id == invoice_id
        )
    ).one()
    return InvoiceDetailOut.model_validate(
        {
            **InvoiceOut.model_validate(invoice).model_dump(),
            "fields": [_field_out(field, threshold) for field in fields],
            "checks": [CheckOut.model_validate(check) for check in ordered],
            "file_url": request.app.url_path_for("get_invoice_file", invoice_id=invoice_id),
            "llm_calls": calls,
            "llm_cost_usd": cost,
        }
    )


def _attachment(filename: str) -> str:
    """Content-Disposition for a download: an ASCII fallback and the UTF-8 name (RFC 6266)."""
    fallback = "".join(
        char if char.isascii() and char.isprintable() and char not in '"\\' else "_"
        for char in filename
    )
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


@router.get(
    "/{invoice_id}/file",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {"content": {"application/xml": {}, "application/pdf": {}}},
        status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Unknown invoice"},
    },
)
def get_invoice_file(invoice_id: uuid.UUID, session: DbSession, request: Request) -> Response:
    """The uploaded file as it was received, as a download (never shown inline)."""
    invoice = get_invoice_or_404(session, invoice_id)
    storage: FileStorage = request.app.state.storage
    return Response(
        storage.read(invoice.storage_path),
        media_type=MEDIA_TYPES[invoice.source_type],
        headers={
            "Content-Disposition": _attachment(invoice.original_filename),
            "X-Content-Type-Options": "nosniff",
        },
    )
