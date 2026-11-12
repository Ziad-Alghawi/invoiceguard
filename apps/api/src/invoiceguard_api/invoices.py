"""Invoice upload, list and detail. Upload schedules background processing (ADR-007)."""

import hashlib
import uuid
from datetime import datetime
from typing import Annotated, Any, BinaryIO

from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from invoiceguard_api.db import DbSession
from invoiceguard_api.filetype import safe_filename, source_type_for
from invoiceguard_api.models import (
    AuditEvent,
    Check,
    CheckStatus,
    Invoice,
    InvoiceStatus,
    SourceType,
)
from invoiceguard_api.processing import process_invoice
from invoiceguard_api.storage import FileStorage

router = APIRouter(prefix="/invoices", tags=["invoices"])

CHUNK_BYTES = 64 * 1024
# Until demo login exists (ADR-006), uploads are not tied to a user.
ANONYMOUS_ACTOR = "anonymous"


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


class InvoiceDetailOut(InvoiceOut):
    # Worst first: failed, warning, skipped, passed.
    checks: list[CheckOut]


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
            actor=ANONYMOUS_ACTOR,
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
        invoice.id,
    )
    response.headers["Location"] = str(request.url_for("get_invoice", invoice_id=invoice.id))
    return InvoiceOut.model_validate(invoice)


@router.get("")
def list_invoices(
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[InvoiceOut]:
    """Invoices, newest first."""
    invoices = session.scalars(
        select(Invoice)
        .order_by(Invoice.created_at.desc(), Invoice.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [InvoiceOut.model_validate(invoice) for invoice in invoices]


@router.get(
    "/{invoice_id}",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Unknown invoice"}},
)
def get_invoice(invoice_id: uuid.UUID, session: DbSession) -> InvoiceDetailOut:
    """The invoice with its check results (empty until processing has run the checks)."""
    invoice = session.get(Invoice, invoice_id)
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invoice not found.")
    checks = session.scalars(select(Check).where(Check.invoice_id == invoice_id)).all()
    ordered = sorted(checks, key=lambda check: (SEVERITY_ORDER.index(check.status), check.type))
    return InvoiceDetailOut.model_validate(
        {
            **InvoiceOut.model_validate(invoice).model_dump(),
            "checks": [CheckOut.model_validate(check) for check in ordered],
        }
    )
