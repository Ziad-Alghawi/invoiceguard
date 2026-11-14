"""DATEV-style export of approved invoices (ADR-013). Needs a logged-in user (ADR-011).

`POST /exports/datev` puts every approved invoice that is not in an export yet into one new
booking file, marks the invoices with the export and audits it, in one transaction. The invoice
rows are locked with FOR UPDATE, so two exports at the same moment cannot both take an invoice:
the second waits, then sees it as exported. An exported invoice never goes into another file;
the explicit way to get it again is to download its export again (`GET .../file`), which is
the same file and is audited too.
"""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from invoiceguard_api import datev
from invoiceguard_api.auth import CurrentUser, current_user
from invoiceguard_api.db import DbSession
from invoiceguard_api.invoices import ErrorOut, attachment
from invoiceguard_api.models import (
    AuditEvent,
    DatevExport,
    Invoice,
    InvoiceField,
    InvoiceStatus,
    User,
)
from invoiceguard_api.settings import Settings

router = APIRouter(prefix="/exports/datev", tags=["exports"], dependencies=[Depends(current_user)])

# The EN 16931 terms a booking needs; line ID (every line has one) and VAT rate per line.
INVOICE_NUMBER, ISSUE_DATE, TYPE_CODE, CURRENCY = "BT-1", "BT-2", "BT-3", "BT-5"
SELLER_NAME, GROSS_TOTAL = "BT-27", "BT-112"
LINE_ID, LINE_VAT_RATE = "BT-126", "BT-152"
DOCUMENT_CODES = (INVOICE_NUMBER, ISSUE_DATE, TYPE_CODE, CURRENCY, SELLER_NAME, GROSS_TOTAL)
# UNTDID 1001 code 381: credit note.
CREDIT_NOTE_TYPE = "381"
MEDIA_TYPE = "text/csv; charset=windows-1252"


class ExportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    invoice_count: int
    fiscal_year_start: date
    date_from: date
    date_to: date
    filename: str


class ExportCreatedOut(ExportOut):
    # Exported without a BU key (several or unconfigured VAT rates): the advisor sets the tax.
    without_tax_key: int
    # Approved invoices still waiting, from a later fiscal year: export again for those.
    remaining: int
    # Download path of the file, relative to the API root.
    file_url: str


def _bookings(
    session: Session, invoices: list[Invoice], tax_keys: dict[Decimal, str]
) -> dict[uuid.UUID, datev.Booking]:
    ids = [invoice.id for invoice in invoices]
    fields = session.scalars(
        select(InvoiceField).where(
            InvoiceField.invoice_id.in_(ids),
            InvoiceField.code.in_((*DOCUMENT_CODES, LINE_ID, LINE_VAT_RATE)),
        )
    )
    terms: dict[uuid.UUID, dict[str, str]] = defaultdict(dict)
    lines: dict[uuid.UUID, set[int]] = defaultdict(set)
    rates: dict[uuid.UUID, dict[int, Decimal]] = defaultdict(dict)
    for field in fields:
        if field.line_no is None:
            terms[field.invoice_id][field.code] = field.value
        elif field.code == LINE_ID:
            lines[field.invoice_id].add(field.line_no)
        else:
            rates[field.invoice_id][field.line_no] = Decimal(field.value)
    bookings = {}
    for invoice in invoices:
        values = terms[invoice.id]
        # One tax key only when every line has a rate, all rates are equal and the rate is
        # configured (ADR-013); a line without a rate (for example exempt) has no BT-152 row.
        line_rates = rates[invoice.id]
        distinct = set(line_rates.values())
        single = lines[invoice.id] and set(line_rates) == lines[invoice.id] and len(distinct) == 1
        tax_key = tax_keys.get(distinct.pop()) if single else None
        bookings[invoice.id] = datev.Booking(
            gross_total=Decimal(values[GROSS_TOTAL]),
            credit_note=values[TYPE_CODE] == CREDIT_NOTE_TYPE,
            currency=values[CURRENCY],
            document_date=date.fromisoformat(values[ISSUE_DATE]),
            invoice_number=values[INVOICE_NUMBER],
            seller_name=values[SELLER_NAME],
            tax_key=tax_key,
        )
    return bookings


def _event(
    user: User, action: str, entity_type: str, entity_id: uuid.UUID, **details: Any
) -> AuditEvent:
    return AuditEvent(
        actor=user.email,
        user_id=user.id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=details,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorOut,
            "description": "No approved invoice is waiting for export",
        }
    },
)
def create_export(
    session: DbSession, user: CurrentUser, request: Request, response: Response
) -> ExportCreatedOut:
    """Export the approved, not yet exported invoices of the oldest fiscal year among them."""
    settings: Settings = request.app.state.settings
    pending = list(
        session.scalars(
            select(Invoice)
            .where(Invoice.status == InvoiceStatus.APPROVED, Invoice.datev_export_id.is_(None))
            .order_by(Invoice.id)
            .with_for_update()
        )
    )
    if not pending:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No approved invoices are waiting for export."
        )
    bookings = _bookings(session, pending, settings.datev_tax_keys)

    def year_of(invoice: Invoice) -> date:
        return datev.fiscal_year_start(
            bookings[invoice.id].document_date, settings.datev_fiscal_year_start_month
        )

    fiscal_year = min(year_of(invoice) for invoice in pending)
    batch_invoices = sorted(
        (invoice for invoice in pending if year_of(invoice) == fiscal_year),
        key=lambda invoice: (
            bookings[invoice.id].document_date,
            bookings[invoice.id].invoice_number,
        ),
    )
    batch_bookings = [bookings[invoice.id] for invoice in batch_invoices]
    created_at = datetime.now(UTC)
    batch = datev.Batch(
        created_at=created_at,
        exported_by=user.display_name,
        advisor_number=settings.datev_advisor_number,
        client_number=settings.datev_client_number,
        fiscal_year_start=fiscal_year,
        account_length=settings.datev_account_length,
        date_from=batch_bookings[0].document_date,
        date_to=batch_bookings[-1].document_date,
        description=f"InvoiceGuard {created_at:%Y-%m-%d}",
        chart_of_accounts=settings.datev_chart_of_accounts,
        creditor_account=settings.datev_creditor_account,
        expense_account=settings.datev_expense_account,
    )
    export = DatevExport(
        id=uuid.uuid4(),
        created_at=created_at,
        user_id=user.id,
        invoice_count=len(batch_invoices),
        fiscal_year_start=fiscal_year,
        date_from=batch.date_from,
        date_to=batch.date_to,
        filename=f"EXTF_Buchungsstapel_{created_at:%Y%m%d_%H%M%S}.csv",
        content=datev.build_csv(batch, batch_bookings),
    )
    without_tax_key = sum(1 for booking in batch_bookings if booking.tax_key is None)
    session.add(export)
    session.add(
        _event(
            user,
            "datev_export.created",
            "datev_export",
            export.id,
            invoice_ids=[str(invoice.id) for invoice in batch_invoices],
            invoice_count=len(batch_invoices),
            without_tax_key=without_tax_key,
            fiscal_year_start=fiscal_year.isoformat(),
        )
    )
    for invoice in batch_invoices:
        invoice.datev_export_id = export.id
        session.add(
            _event(user, "invoice.exported", "invoice", invoice.id, export_id=str(export.id))
        )
    session.commit()

    file_url = request.app.url_path_for("get_export_file", export_id=export.id)
    response.headers["Location"] = file_url
    return ExportCreatedOut.model_validate(
        {
            **ExportOut.model_validate(export).model_dump(),
            "without_tax_key": without_tax_key,
            "remaining": len(pending) - len(batch_invoices),
            "file_url": file_url,
        }
    )


@router.get(
    "/{export_id}/file",
    response_class=Response,
    responses={
        status.HTTP_200_OK: {"content": {"text/csv": {}}},
        status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Unknown export"},
    },
)
def get_export_file(export_id: uuid.UUID, session: DbSession, user: CurrentUser) -> Response:
    """The booking file of an export, byte for byte as created; every download is audited."""
    export = session.get(DatevExport, export_id)
    if export is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not found.")
    session.add(_event(user, "datev_export.downloaded", "datev_export", export.id))
    session.commit()
    return Response(
        export.content,
        media_type=MEDIA_TYPE,
        headers={
            "Content-Disposition": attachment(export.filename),
            "X-Content-Type-Options": "nosniff",
        },
    )
