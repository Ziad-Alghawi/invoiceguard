"""Load everything the checks need from the database, once, into a `CheckContext`."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from invoiceguard_api.checks.model import (
    CheckContext,
    KnownSupplier,
    Order,
    OrderLine,
    OtherInvoice,
    Validation,
    VerifiedIban,
)
from invoiceguard_api.checks.supplier import normalise_vat_id
from invoiceguard_api.models import Invoice, InvoiceField, PurchaseOrder, Supplier
from invoiceguard_api.parsing import ParsedInvoice

SELLER_VAT_ID = "BT-31"
SELLER_NAME = "BT-27"
DUPLICATE_TERMS = ("BT-1", "BT-2", "BT-112")


def _supplier(session: Session, vat_id: str | None) -> KnownSupplier | None:
    if vat_id is None:
        return None
    supplier = session.scalar(
        select(Supplier)
        .where(Supplier.vat_id == normalise_vat_id(vat_id))
        .options(selectinload(Supplier.bank_accounts))
    )
    if supplier is None:
        return None
    return KnownSupplier(
        id=supplier.id,
        name=supplier.name,
        vat_id=supplier.vat_id,
        verified_ibans=tuple(
            VerifiedIban(account.iban, account.since, account.verified_by)
            for account in supplier.bank_accounts
            if account.verified
        ),
    )


def _order(session: Session, reference: str | None) -> Order | None:
    if reference is None:
        return None
    order = session.scalar(
        select(PurchaseOrder)
        .where(PurchaseOrder.number == reference.strip())
        .options(selectinload(PurchaseOrder.lines))
    )
    if order is None:
        return None
    return Order(
        id=order.id,
        number=order.number,
        supplier_id=order.supplier_id,
        currency=order.currency,
        lines=tuple(
            OrderLine(
                line.line_no, line.description, line.quantity, line.unit_code, line.unit_price
            )
            for line in order.lines
        ),
    )


def _other_invoices(
    session: Session, invoice_id: uuid.UUID, parsed: ParsedInvoice
) -> tuple[OtherInvoice, ...]:
    """Stored invoices of the same seller: by VAT ID, or by exact name when there is none.

    BT-1, BT-2 and BT-112 are required terms, so every stored invoice has a row for each.
    """
    if parsed.seller_vat_id is not None:
        seller_matches = (InvoiceField.code == SELLER_VAT_ID) & (
            func.upper(func.regexp_replace(InvoiceField.value, "[^0-9A-Za-z]", "", "g"))
            == normalise_vat_id(parsed.seller_vat_id)
        )
    else:
        seller_matches = (InvoiceField.code == SELLER_NAME) & (
            InvoiceField.value == parsed.seller_name
        )
    same_seller = (
        select(InvoiceField.invoice_id)
        .where(
            seller_matches, InvoiceField.line_no.is_(None), InvoiceField.invoice_id != invoice_id
        )
        .scalar_subquery()
    )
    rows = session.execute(
        select(Invoice.id, Invoice.status, InvoiceField.code, InvoiceField.value)
        .join(InvoiceField, InvoiceField.invoice_id == Invoice.id)
        .where(
            Invoice.id.in_(same_seller),
            InvoiceField.code.in_(DUPLICATE_TERMS),
            InvoiceField.line_no.is_(None),
        )
        .order_by(Invoice.created_at, Invoice.id)
    ).all()
    terms: dict[uuid.UUID, dict[str, str]] = {}
    statuses: dict[uuid.UUID, str] = {}
    for other_id, status, code, value in rows:
        terms.setdefault(other_id, {})[code] = value
        statuses[other_id] = status.value
    return tuple(
        OtherInvoice(
            id=other_id,
            invoice_number=values["BT-1"],
            issue_date=date.fromisoformat(values["BT-2"]),
            gross_total=Decimal(values["BT-112"]),
            status=statuses[other_id],
        )
        for other_id, values in terms.items()
    )


def load_context(
    session: Session, invoice_id: uuid.UUID, parsed: ParsedInvoice, validation: Validation
) -> CheckContext:
    return CheckContext(
        invoice=parsed,
        validation=validation,
        supplier=_supplier(session, parsed.seller_vat_id),
        order=_order(session, parsed.order_reference),
        other_invoices=_other_invoices(session, invoice_id, parsed),
    )
