"""The registry tools against the seeded demo data, called through an in-process MCP client, as
the server's own read-only role."""

from typing import Any

import pytest
from mcp import Client
from mcp.server import MCPServer
from psycopg import errors

from invoiceguard_mcp_registry import server as registry
from invoiceguard_mcp_registry.db import Database

pytestmark = pytest.mark.anyio

IT_SERVICE = "DE999000033"
IT_SERVICE_IBAN = "DE60123456780000000003"
# The changed IBAN on demo sample 02: a valid checksum, but no supplier has it.
FOREIGN_IBAN = "DE58876543210000000099"  # pragma: allowlist secret


@pytest.fixture
def server(database: Database) -> MCPServer:
    return registry.build_server(database)


async def call(server: MCPServer, tool: str, arguments: dict[str, Any]) -> Any:
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    return result.structured_content


async def test_lists_only_the_read_only_tools(server: MCPServer) -> None:
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == {"check_vat_id", "check_iban", "get_bank_accounts"}
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools)


async def test_check_vat_id_of_a_known_supplier(server: MCPServer) -> None:
    result = await call(server, "check_vat_id", {"vat_id": IT_SERVICE})
    assert result["checksum"] == "valid"
    assert result["known_supplier"] == {
        "name": "Demo IT-Service GmbH",
        "vat_id": IT_SERVICE,
        "country_code": "DE",
    }


@pytest.mark.parametrize(
    ("vat_id", "checksum"),
    [("DE999000034", "invalid"), ("DE12345", "invalid"), ("ATU12345678", "not_checked")],
)
async def test_check_vat_id_of_an_unknown_id(server: MCPServer, vat_id: str, checksum: str) -> None:
    result = await call(server, "check_vat_id", {"vat_id": vat_id})
    assert result["checksum"] == checksum
    assert result["known_supplier"] is None


async def test_check_iban_registered_to_the_supplier(server: MCPServer) -> None:
    result = await call(server, "check_iban", {"iban": IT_SERVICE_IBAN})
    assert result["checksum_valid"] is True
    assert result["registered_to"] == [
        {
            "supplier_name": "Demo IT-Service GmbH",
            "supplier_vat_id": IT_SERVICE,
            "verified": True,
            "since": "2025-01-10",
            "verified_by": "Stammdatenpflege (Demo)",
        }
    ]


async def test_check_iban_not_in_the_registry(server: MCPServer) -> None:
    result = await call(server, "check_iban", {"iban": FOREIGN_IBAN})
    assert result == {"iban": FOREIGN_IBAN, "checksum_valid": True, "registered_to": []}


async def test_check_iban_with_a_wrong_checksum(server: MCPServer) -> None:
    result = await call(server, "check_iban", {"iban": "DE60123456780000000004"})
    assert result["checksum_valid"] is False


async def test_get_bank_accounts(server: MCPServer) -> None:
    result = await call(server, "get_bank_accounts", {"vat_id": IT_SERVICE})
    assert result["supplier_name"] == "Demo IT-Service GmbH"
    assert [account["iban"] for account in result["accounts"]] == [IT_SERVICE_IBAN]


async def test_get_bank_accounts_of_an_unknown_supplier(server: MCPServer) -> None:
    result = await call(server, "get_bank_accounts", {"vat_id": "DE123456789"})
    assert result == {
        "vat_id": "DE123456789",
        "supplier_found": False,
        "supplier_name": None,
        "accounts": [],
    }


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("check_iban", {"iban": "DE60 1234 5678 0000 0000 03"}),
        ("check_iban", {"iban": "' OR 1=1 --"}),
        ("check_vat_id", {"vat_id": "DE999000033; DELETE FROM suppliers"}),
        ("get_bank_accounts", {}),
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
        result = await client.call_tool("verify_iban", {"iban": FOREIGN_IBAN})
    assert result.is_error


def test_connection_is_read_only(database: Database) -> None:
    with pytest.raises(errors.ReadOnlySqlTransaction):
        database.rows("CREATE TEMP TABLE scratch (id int)")


@pytest.mark.parametrize(
    "query",
    ["SELECT contact_email FROM suppliers", "SELECT * FROM purchase_orders"],
)
def test_role_cannot_read_other_data(database: Database, query: str) -> None:
    with pytest.raises(errors.InsufficientPrivilege):
        database.rows(query)


def test_transport_security_allows_only_the_given_hosts() -> None:
    settings = registry.transport_security(["mcp-registry:*"])
    assert settings.allowed_hosts == ["mcp-registry:*"]
    assert settings.allowed_origins == []
