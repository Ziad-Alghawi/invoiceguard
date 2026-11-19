"""The read model of `mcp-history` (migration 0013): what its views show and what they leave out.

Only imported history and approved invoices that did not fail the prompt-injection check are
history, and only their searchable bookings; `invoice_item_names` gives line names, nothing else.
"""

import secrets
import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from invoiceguard_api.booking.text import normalise, text_sha256
from invoiceguard_api.checks.injection import CHECK_TYPE as INJECTION_CHECK
from invoiceguard_api.models import (
    Booking,
    BookingSource,
    Check,
    CheckStatus,
    FieldSource,
    Invoice,
    InvoiceField,
    InvoiceStatus,
    SourceType,
)

VAT_ID = "DE999000033"


def add_invoice(session: Session, status: InvoiceStatus, *, injected: bool = False) -> uuid.UUID:
    invoice = Invoice(
        status=status,
        source_type=SourceType.XML,
        original_filename="r.xml",
        sha256=secrets.token_hex(32),
        size_bytes=1,
        storage_path="x",
    )
    session.add(invoice)
    session.flush()
    for code, line_no, value in (
        ("BT-5", None, "EUR"),
        ("BT-109", None, "100.00"),
        ("BT-112", None, "119.00"),
        ("BT-84", None, "DE60123456780000000003"),
        ("BT-153", 1, "Kopierpapier A4"),
        ("BT-131", 1, "100.00"),
    ):
        session.add(
            InvoiceField(
                invoice_id=invoice.id,
                code=code,
                line_no=line_no,
                value=value,
                source=FieldSource.XML,
            )
        )
    if injected:
        session.add(
            Check(
                invoice_id=invoice.id,
                type=INJECTION_CHECK,
                status=CheckStatus.FAILED,
                message="Instruction-like text.",
            )
        )
    session.flush()
    return invoice.id


def add_booking(
    session: Session, invoice_id: uuid.UUID | None, line: str, *, searchable: bool = True
) -> None:
    normalised = normalise(line)
    session.add(
        Booking(
            source=BookingSource.IMPORT if invoice_id is None else BookingSource.INVOICE,
            invoice_id=invoice_id,
            line_no=1,
            supplier_vat_id=VAT_ID,
            supplier_name="Lieferant",
            invoice_number=line,
            issue_date=date(2026, 3, 1),
            text=normalised,
            text_sha256=text_sha256(normalised),
            account="4930",
            suggested_account=None,
            searchable=searchable,
        )
    )
    session.flush()


def history_texts(session: Session) -> set[str]:
    return set(session.scalars(text("SELECT text FROM history_lines")))


def test_history_holds_imports_and_clean_approved_invoices_only(db_session: Session) -> None:
    approved = add_invoice(db_session, InvoiceStatus.APPROVED)
    flagged = add_invoice(db_session, InvoiceStatus.APPROVED, injected=True)
    rejected = add_invoice(db_session, InvoiceStatus.REJECTED)
    add_booking(db_session, None, "imported")
    add_booking(db_session, approved, "approved")
    add_booking(db_session, flagged, "flagged")
    add_booking(db_session, rejected, "rejected")
    add_booking(db_session, None, "unsearchable", searchable=False)

    assert history_texts(db_session) == {"imported", "approved"}
    invoices = db_session.execute(text("SELECT * FROM history_invoices")).mappings().all()
    assert [dict(row) for row in invoices] == [
        {
            "invoice_id": approved,
            "currency": "EUR",
            "net_total": "100.00",
            "gross_total": "119.00",
            "payee_iban": "DE60123456780000000003",
        }
    ]


def test_item_names_are_the_only_invoice_text_shown(db_session: Session) -> None:
    invoice_id = add_invoice(db_session, InvoiceStatus.BLOCKED)

    rows = db_session.execute(text("SELECT * FROM invoice_item_names")).mappings().all()

    assert [dict(row) for row in rows] == [
        {"invoice_id": invoice_id, "line_no": 1, "item_name": "Kopierpapier A4"}
    ]
