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
from dataclasses import dataclass
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
    BookingSource,
    DatevExport,
    Invoice,
    InvoiceField,
    InvoiceStatus,
    User,
)
from invoiceguard_api.models import Booking as ChosenAccount
from invoiceguard_api.settings import Settings

router = APIRouter(prefix="/exports/datev", tags=["exports"], dependencies=[Depends(current_user)])

# The EN 16931 terms the booking rows need: document terms and totals, and per line its ID
# (every line has one), net amount and VAT rate.
INVOICE_NUMBER, ISSUE_DATE, TYPE_CODE, CURRENCY = "BT-1", "BT-2", "BT-3", "BT-5"
SELLER_NAME, GROSS_TOTAL = "BT-27", "BT-112"
ALLOWANCE_TOTAL, CHARGE_TOTAL, NET_TOTAL, TAX_TOTAL = "BT-107", "BT-108", "BT-109", "BT-110"
LINE_ID, LINE_NET, LINE_VAT_RATE = "BT-126", "BT-131", "BT-152"
DOCUMENT_CODES = (
    INVOICE_NUMBER,
    ISSUE_DATE,
    TYPE_CODE,
    CURRENCY,
    SELLER_NAME,
    GROSS_TOTAL,
    ALLOWANCE_TOTAL,
    CHARGE_TOTAL,
    NET_TOTAL,
    TAX_TOTAL,
)
LINE_CODES = (LINE_ID, LINE_NET, LINE_VAT_RATE)
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
    # Invoices with a row without a BU key (several or unconfigured VAT rates on one row, or a
    # line without a rate): the advisor sets the tax.
    without_tax_key: int
    # Invoices with chosen accounts whose lines do not add up to the totals (for example a
    # document allowance): exported as one row, the advisor splits them by account.
    without_account_split: int
    # Approved invoices still waiting, from a later fiscal year: export again for those.
    remaining: int
    # Download path of the file, relative to the API root.
    file_url: str


@dataclass(frozen=True)
class InvoiceRows:
    """The booking rows of one invoice."""

    rows: list[datev.Booking]
    # The reviewer chose accounts, but the lines do not add up to the invoice's totals: one row.
    split_failed: bool

    @property
    def document_date(self) -> date:
        return self.rows[0].document_date

    @property
    def invoice_number(self) -> str:
        return self.rows[0].invoice_number


def _amount(values: dict[str, str], code: str) -> Decimal:
    """A document amount; an absent optional total (BT-107, BT-108, BT-110) is zero."""
    return Decimal(values.get(code, "0"))


def _split(
    values: dict[str, str], line_terms: dict[int, dict[str, str]], accounts: dict[int, str]
) -> list[datev.Part] | None:
    """The parts per chosen account and VAT rate; None unless every line has an account and a
    net amount and the parts add up to the invoice's totals."""
    if set(accounts) != set(line_terms) or any(LINE_NET not in t for t in line_terms.values()):
        return None
    lines = [
        datev.Line(
            account=accounts[line_no],
            net_amount=Decimal(terms[LINE_NET]),
            vat_rate=Decimal(terms[LINE_VAT_RATE]) if LINE_VAT_RATE in terms else None,
        )
        for line_no, terms in sorted(line_terms.items())
    ]
    totals = datev.Totals(
        net_total=_amount(values, NET_TOTAL),
        tax_total=_amount(values, TAX_TOTAL),
        gross_total=_amount(values, GROSS_TOTAL),
        allowances_or_charges=bool(
            _amount(values, ALLOWANCE_TOTAL) or _amount(values, CHARGE_TOTAL)
        ),
    )
    return datev.split_by_account(lines, totals)


def _single_tax_key(
    line_terms: dict[int, dict[str, str]], tax_keys: dict[Decimal, str]
) -> str | None:
    """One tax key only when every line has a rate, all rates are equal and the rate is
    configured (ADR-013); a line without a rate (for example exempt) has no BT-152 row."""
    if not line_terms or any(LINE_VAT_RATE not in terms for terms in line_terms.values()):
        return None
    rates = {Decimal(terms[LINE_VAT_RATE]) for terms in line_terms.values()}
    return tax_keys.get(rates.pop()) if len(rates) == 1 else None


def _invoice_rows(
    values: dict[str, str],
    line_terms: dict[int, dict[str, str]],
    accounts: dict[int, str],
    settings: Settings,
) -> InvoiceRows:
    """One row per (chosen account, VAT rate) when the split adds up, else one row (ADR-013)."""

    def row(gross: Decimal, account: str, tax_key: str | None) -> datev.Booking:
        return datev.Booking(
            gross_total=gross,
            account=account,
            credit_note=values[TYPE_CODE] == CREDIT_NOTE_TYPE,
            currency=values[CURRENCY],
            document_date=date.fromisoformat(values[ISSUE_DATE]),
            invoice_number=values[INVOICE_NUMBER],
            seller_name=values[SELLER_NAME],
            tax_key=tax_key,
        )

    tax_keys = settings.datev_tax_keys
    parts = _split(values, line_terms, accounts) if accounts else None
    if parts is not None:
        return InvoiceRows(
            [
                row(
                    part.gross,
                    part.account,
                    None if part.vat_rate is None else tax_keys.get(part.vat_rate),
                )
                for part in parts
            ],
            split_failed=False,
        )
    # Every line booked to one account: that account, else the configured expense account.
    chosen = set(accounts.values())
    account = chosen.pop() if len(chosen) == 1 else settings.datev_expense_account
    gross = Decimal(values[GROSS_TOTAL])
    return InvoiceRows(
        [row(gross, account, _single_tax_key(line_terms, tax_keys))], split_failed=bool(accounts)
    )


def _rows(
    session: Session, invoices: list[Invoice], settings: Settings
) -> dict[uuid.UUID, InvoiceRows]:
    ids = [invoice.id for invoice in invoices]
    fields = session.scalars(
        select(InvoiceField).where(
            InvoiceField.invoice_id.in_(ids),
            InvoiceField.code.in_((*DOCUMENT_CODES, *LINE_CODES)),
        )
    )
    terms: dict[uuid.UUID, dict[str, str]] = defaultdict(dict)
    lines: dict[uuid.UUID, dict[int, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    for field in fields:
        if field.line_no is None:
            terms[field.invoice_id][field.code] = field.value
        else:
            lines[field.invoice_id][field.line_no][field.code] = field.value
    # The accounts reviewers chose per line when approving (ADR-020): all lines or none.
    # Keyed like the column (nullable for imported history, which the query leaves out).
    accounts: dict[uuid.UUID | None, dict[int, str]] = defaultdict(dict)
    chosen = session.execute(
        select(ChosenAccount.invoice_id, ChosenAccount.line_no, ChosenAccount.account).where(
            ChosenAccount.source == BookingSource.INVOICE, ChosenAccount.invoice_id.in_(ids)
        )
    )
    for invoice_id, line_no, account in chosen:
        accounts[invoice_id][line_no] = account
    return {
        invoice.id: _invoice_rows(
            terms[invoice.id], lines[invoice.id], accounts[invoice.id], settings
        )
        for invoice in invoices
    }


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
    rows = _rows(session, pending, settings)

    def year_of(invoice: Invoice) -> date:
        return datev.fiscal_year_start(
            rows[invoice.id].document_date, settings.datev_fiscal_year_start_month
        )

    fiscal_year = min(year_of(invoice) for invoice in pending)
    batch_invoices = sorted(
        (invoice for invoice in pending if year_of(invoice) == fiscal_year),
        key=lambda invoice: (rows[invoice.id].document_date, rows[invoice.id].invoice_number),
    )
    batch_rows = [rows[invoice.id] for invoice in batch_invoices]
    created_at = datetime.now(UTC)
    batch = datev.Batch(
        created_at=created_at,
        exported_by=user.display_name,
        advisor_number=settings.datev_advisor_number,
        client_number=settings.datev_client_number,
        fiscal_year_start=fiscal_year,
        account_length=settings.datev_account_length,
        date_from=batch_rows[0].document_date,
        date_to=batch_rows[-1].document_date,
        description=f"InvoiceGuard {created_at:%Y-%m-%d}",
        chart_of_accounts=settings.datev_chart_of_accounts,
        creditor_account=settings.datev_creditor_account,
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
        content=datev.build_csv(batch, [row for invoice in batch_rows for row in invoice.rows]),
    )
    without_tax_key = sum(
        1 for invoice in batch_rows if any(row.tax_key is None for row in invoice.rows)
    )
    without_account_split = sum(1 for invoice in batch_rows if invoice.split_failed)
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
            without_account_split=without_account_split,
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
            "without_account_split": without_account_split,
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
