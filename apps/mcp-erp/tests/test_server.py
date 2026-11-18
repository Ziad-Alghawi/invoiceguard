"""The ERP tools against the seeded demo data, called through an in-process MCP client, as the
server's own read-only role."""

from typing import Any

import pytest
from mcp import Client
from mcp.server import MCPServer
from psycopg import errors

from invoiceguard_mcp_erp import server as erp
from invoiceguard_mcp_erp.db import Database

pytestmark = pytest.mark.anyio

IT_SERVICE = "DE999000033"


@pytest.fixture
def server(database: Database) -> MCPServer:
    return erp.build_server(database)


async def call(server: MCPServer, tool: str, arguments: dict[str, Any]) -> Any:
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    return result.structured_content


async def test_lists_only_the_read_only_tools(server: MCPServer) -> None:
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == {
        "get_supplier",
        "list_purchase_orders",
        "get_purchase_order",
        "get_goods_receipts",
    }
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools)
    assert all(tool.output_schema for tool in tools)


async def test_get_supplier(server: MCPServer) -> None:
    result = await call(server, "get_supplier", {"vat_id": IT_SERVICE})
    assert result["found"] is True
    assert result["supplier"]["name"] == "Demo IT-Service GmbH"
    assert result["supplier"]["contact_email"] == "buchhaltung@demo-it-service.example"


async def test_unknown_supplier_is_not_found(server: MCPServer) -> None:
    result = await call(server, "get_supplier", {"vat_id": "DE123456789"})
    assert result == {"found": False, "supplier": None}


async def test_list_purchase_orders_newest_first(server: MCPServer) -> None:
    result = await call(server, "list_purchase_orders", {"vat_id": IT_SERVICE})
    assert [order["number"] for order in result["orders"]] == ["PO-2026-0006", "PO-2026-0005"]
    assert result["orders"][1]["net_amount"] == "4317.00"
    assert result["orders"][1]["line_count"] == 2


async def test_get_purchase_order_with_received_quantities(server: MCPServer) -> None:
    result = await call(server, "get_purchase_order", {"number": "PO-2026-0009"})
    order = result["order"]
    assert order["supplier_vat_id"] == "DE999000050"
    assert order["net_amount"] == "1492.00"
    assert [(line["quantity"], line["received_quantity"]) for line in order["lines"]] == [
        ("8.000", "8.000"),
        ("1.000", "0"),
    ]


async def test_unknown_order_is_not_found(server: MCPServer) -> None:
    result = await call(server, "get_purchase_order", {"number": "PO-1999-0001"})
    assert result == {"found": False, "order": None}


async def test_get_goods_receipts(server: MCPServer) -> None:
    result = await call(server, "get_goods_receipts", {"po_number": "PO-2026-0004"})
    assert result["order_found"] is True
    assert result["receipts"] == [
        {"number": "WE-2026-0003", "received_on": "2026-10-22",
         "lines": [{"po_line_no": 1, "quantity": "1.000"}]},
    ]  # fmt: skip


async def test_order_without_delivery_has_no_receipts(server: MCPServer) -> None:
    result = await call(server, "get_goods_receipts", {"po_number": "PO-2026-0002"})
    assert result == {"po_number": "PO-2026-0002", "order_found": True, "receipts": []}


async def test_receipts_of_an_unknown_order(server: MCPServer) -> None:
    result = await call(server, "get_goods_receipts", {"po_number": "PO-1999-0001"})
    assert result["order_found"] is False


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_supplier", {"vat_id": "DE999' OR '1'='1"}),
        ("get_supplier", {"vat_id": "de999000033"}),
        ("get_purchase_order", {"number": "PO; DROP TABLE suppliers"}),
        ("get_goods_receipts", {"po_number": "x" * 51}),
        ("get_supplier", {}),
    ],
)
async def test_invalid_input_is_refused_before_any_query(
    server: MCPServer, tool: str, arguments: dict[str, Any]
) -> None:
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    assert result.is_error


async def test_unknown_tool_is_refused(server: MCPServer) -> None:
    async with Client(server) as client:
        result = await client.call_tool("update_supplier", {"vat_id": IT_SERVICE})
    assert result.is_error


def test_connection_is_read_only(database: Database) -> None:
    with pytest.raises(errors.ReadOnlySqlTransaction):
        database.rows("CREATE TEMP TABLE scratch (id int)")


def test_role_cannot_read_bank_accounts(database: Database) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        database.rows("SELECT iban FROM supplier_bank_accounts")


def test_transport_security_allows_only_the_given_hosts() -> None:
    settings = erp.transport_security(["mcp-erp:*"])
    assert settings.enable_dns_rebinding_protection
    assert settings.allowed_hosts == ["mcp-erp:*"]
    assert settings.allowed_origins == []
