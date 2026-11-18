"""mcp-erp: a read-only MCP server with mock ERP data for the exception agent (ADR-017).

Tools: supplier master data, purchase orders with what was received, and goods receipts. Each
tool has a typed input (validated against a pattern before any query) and a typed output with a
bounded size. Nothing here writes, and there is no tool that takes SQL.

Run with `invoiceguard-mcp-erp` (streamable HTTP on port 8000, path /mcp).
"""

import os
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from invoiceguard_mcp_erp.db import Database

# A VAT ID as printed on invoices (BT-31): country code, then 2 to 13 letters or digits.
VatId = Annotated[
    str,
    Field(pattern=r"^[A-Z]{2}[0-9A-Z]{2,13}$", description="VAT ID, e.g. DE999000033"),
]
OrderNumber = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9./_-]{0,49}$",
        description="Purchase order number (BT-13), e.g. PO-2026-0005",
    ),
]
# Enough for the agent; a supplier with more orders gets the newest ones.
MAX_ORDERS = 20
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


class Supplier(BaseModel):
    vat_id: str
    name: str
    street: str
    postal_code: str
    city: str
    country_code: str
    # Where supplier emails go; an address printed on an invoice may not be the supplier's.
    contact_email: str | None


class SupplierResult(BaseModel):
    found: bool
    supplier: Supplier | None


class OrderSummary(BaseModel):
    number: str
    order_date: date
    currency: str
    net_amount: Decimal
    line_count: int


class OrderList(BaseModel):
    vat_id: str
    orders: list[OrderSummary]


class OrderLine(BaseModel):
    line_no: int
    description: str
    quantity: Decimal
    unit_code: str
    unit_price: Decimal
    vat_rate: Decimal
    net_amount: Decimal
    # Summed over all goods receipts for the order.
    received_quantity: Decimal


class Order(BaseModel):
    number: str
    supplier_vat_id: str
    supplier_name: str
    order_date: date
    currency: str
    net_amount: Decimal
    lines: list[OrderLine]


class OrderResult(BaseModel):
    found: bool
    order: Order | None


class ReceiptLine(BaseModel):
    po_line_no: int
    quantity: Decimal


class Receipt(BaseModel):
    number: str
    received_on: date
    lines: list[ReceiptLine]


class ReceiptList(BaseModel):
    po_number: str
    order_found: bool
    receipts: list[Receipt]


SUPPLIER_SQL = """
SELECT vat_id, name, street, postal_code, city, country_code, contact_email
FROM suppliers WHERE vat_id = %(vat_id)s
"""
ORDERS_SQL = """
SELECT o.number, o.order_date, o.currency,
       COALESCE(SUM(ROUND(l.quantity * l.unit_price, 2)), 0) AS net_amount,
       COUNT(l.id) AS line_count
FROM purchase_orders o
JOIN suppliers s ON s.id = o.supplier_id
LEFT JOIN purchase_order_lines l ON l.purchase_order_id = o.id
WHERE s.vat_id = %(vat_id)s
GROUP BY o.id
ORDER BY o.order_date DESC, o.number DESC
LIMIT %(limit)s
"""
ORDER_SQL = """
SELECT o.id, o.number, o.order_date, o.currency, s.vat_id AS supplier_vat_id,
       s.name AS supplier_name
FROM purchase_orders o JOIN suppliers s ON s.id = o.supplier_id
WHERE o.number = %(number)s
"""
ORDER_LINES_SQL = """
SELECT l.line_no, l.description, l.quantity, l.unit_code, l.unit_price, l.vat_rate,
       ROUND(l.quantity * l.unit_price, 2) AS net_amount,
       COALESCE((
           SELECT SUM(rl.quantity) FROM goods_receipt_lines rl
           JOIN goods_receipts r ON r.id = rl.goods_receipt_id
           WHERE r.purchase_order_id = l.purchase_order_id AND rl.po_line_no = l.line_no
       ), 0) AS received_quantity
FROM purchase_order_lines l
WHERE l.purchase_order_id = %(order_id)s
ORDER BY l.line_no
"""
RECEIPTS_SQL = """
SELECT r.number, r.received_on, rl.po_line_no, rl.quantity
FROM goods_receipts r
JOIN purchase_orders o ON o.id = r.purchase_order_id
LEFT JOIN goods_receipt_lines rl ON rl.goods_receipt_id = r.id
WHERE o.number = %(number)s
ORDER BY r.received_on, r.number, rl.po_line_no
"""


def _receipts(rows: list[dict[str, Any]]) -> list[Receipt]:
    receipts: dict[str, Receipt] = {}
    for row in rows:
        receipt = receipts.setdefault(
            row["number"], Receipt(number=row["number"], received_on=row["received_on"], lines=[])
        )
        if row["po_line_no"] is not None:
            receipt.lines.append(
                ReceiptLine(po_line_no=row["po_line_no"], quantity=row["quantity"])
            )
    return list(receipts.values())


def build_server(database: Database) -> MCPServer:
    server = MCPServer(
        name="invoiceguard-mcp-erp",
        instructions="Read-only mock ERP data: suppliers, purchase orders, goods receipts.",
        version="0.1.0",
    )

    @server.tool(annotations=READ_ONLY)
    def get_supplier(vat_id: VatId) -> SupplierResult:
        """Supplier master data (name, address, contact email) by VAT ID."""
        rows = database.rows(SUPPLIER_SQL, {"vat_id": vat_id})
        return SupplierResult(
            found=bool(rows), supplier=Supplier.model_validate(rows[0]) if rows else None
        )

    @server.tool(annotations=READ_ONLY)
    def list_purchase_orders(vat_id: VatId) -> OrderList:
        """The supplier's purchase orders, newest first (at most 20), with net amounts."""
        rows = database.rows(ORDERS_SQL, {"vat_id": vat_id, "limit": MAX_ORDERS})
        return OrderList(vat_id=vat_id, orders=[OrderSummary.model_validate(r) for r in rows])

    @server.tool(annotations=READ_ONLY)
    def get_purchase_order(number: OrderNumber) -> OrderResult:
        """One purchase order with its lines and the quantity received so far per line."""
        rows = database.rows(ORDER_SQL, {"number": number})
        if not rows:
            return OrderResult(found=False, order=None)
        header = rows[0]
        lines = [
            OrderLine.model_validate(row)
            for row in database.rows(ORDER_LINES_SQL, {"order_id": header["id"]})
        ]
        net = sum((line.net_amount for line in lines), Decimal("0"))
        return OrderResult(
            found=True, order=Order.model_validate({**header, "net_amount": net, "lines": lines})
        )

    @server.tool(annotations=READ_ONLY)
    def get_goods_receipts(po_number: OrderNumber) -> ReceiptList:
        """The goods receipts (deliveries) booked against a purchase order."""
        found = bool(database.rows(ORDER_SQL, {"number": po_number}))
        rows = database.rows(RECEIPTS_SQL, {"number": po_number}) if found else []
        return ReceiptList(po_number=po_number, order_found=found, receipts=_receipts(rows))

    return server


def transport_security(allowed_hosts: list[str]) -> TransportSecuritySettings:
    """Only these Host headers are served (DNS rebinding protection); no browser origin."""
    return TransportSecuritySettings(allowed_hosts=allowed_hosts, allowed_origins=[])


def main() -> None:
    database = Database(os.environ["INVOICEGUARD_MCP_ERP_DATABASE_URL"])
    hosts = os.environ.get("INVOICEGUARD_MCP_ALLOWED_HOSTS", "mcp-erp:*,localhost:*,127.0.0.1:*")
    build_server(database).run(
        "streamable-http",
        # All interfaces inside the container; Compose decides who can reach the port.
        host="0.0.0.0",
        port=int(os.environ.get("INVOICEGUARD_MCP_PORT", "8000")),
        stateless_http=True,
        json_response=True,
        transport_security=transport_security(hosts.split(",")),
    )
