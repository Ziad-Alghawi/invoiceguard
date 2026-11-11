"""Map a parsed invoice to EN 16931 business-term rows for the `invoice_fields` table."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from invoiceguard_api.parsing.model import ParsedInvoice

DOCUMENT_TERMS = {
    "invoice_number": "BT-1",
    "issue_date": "BT-2",
    "type_code": "BT-3",
    "currency": "BT-5",
    "due_date": "BT-9",
    "seller_name": "BT-27",
    "seller_vat_id": "BT-31",
    "buyer_name": "BT-44",
    "buyer_vat_id": "BT-48",
    "payee_iban": "BT-84",
    "net_total": "BT-109",
    "tax_total": "BT-110",
    "gross_total": "BT-112",
    "amount_due": "BT-115",
}

LINE_TERMS = {
    "line_id": "BT-126",
    "quantity": "BT-129",
    "unit_code": "BT-130",
    "net_amount": "BT-131",
    "net_price": "BT-146",
    "vat_rate": "BT-152",
    "item_name": "BT-153",
}


@dataclass(frozen=True)
class FieldRow:
    code: str
    # None for document-level terms; the 1-based position for line terms.
    line_no: int | None
    value: str


def _text(value: str | date | Decimal) -> str:
    # Decimals keep the scale written in the XML ("100.00" stays "100.00").
    return value.isoformat() if isinstance(value, date) else str(value)


def to_field_rows(invoice: ParsedInvoice) -> list[FieldRow]:
    """One row per term that has a value; absent optional terms (for example BT-84) get no row."""
    rows = [
        FieldRow(code, None, _text(value))
        for name, code in DOCUMENT_TERMS.items()
        if (value := getattr(invoice, name)) is not None
    ]
    for line_no, line in enumerate(invoice.lines, start=1):
        rows.extend(
            FieldRow(code, line_no, _text(value))
            for name, code in LINE_TERMS.items()
            if (value := getattr(line, name)) is not None
        )
    return rows
