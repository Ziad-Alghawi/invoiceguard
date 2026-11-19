"""The history tools against the imported booking history and the rulebook, called through an
in-process MCP client, as the server's own read-only role."""

import secrets
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from mcp import Client
from mcp.server import MCPServer

from invoiceguard_mcp_history import server as history
from invoiceguard_mcp_history.db import Database

pytestmark = pytest.mark.anyio

MODEL = "gemini/gemini-embedding-001"
IT_SERVICE = "DE999000033"
# A booked text with a packaged vector, and one that is in the history by text only.
VECTOR_TEXT = "Fernwartung Arbeitsplatzrechner"


@pytest.fixture
def server(database: Database) -> MCPServer:
    return history.build_server(database, MODEL)


async def call(server: MCPServer, tool: str, arguments: dict[str, Any]) -> Any:
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    assert not result.is_error, result.content
    return result.structured_content


async def refused(server: MCPServer, tool: str, arguments: dict[str, Any]) -> bool:
    async with Client(server) as client:
        return (await client.call_tool(tool, arguments)).is_error


@pytest.fixture
def invoice_with_lines(admin_url: str) -> Iterator[tuple[str, str]]:
    """A blocked invoice with two lines: one booked before (it has a vector), one new wording
    (text match only). Removed afterwards, so other tests see the seeded data only."""
    invoice_id = str(uuid.uuid4())
    new_text = "Fernwartung der Arbeitsplatzrechner im Juni"
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO invoices (id, status, source_type, original_filename, sha256, size_bytes,"
            " storage_path) VALUES (%s, 'blocked', 'xml', 'x.xml', %s, 1, 'x')",
            (invoice_id, secrets.token_hex(32)),
        )
        for line_no, text in ((1, VECTOR_TEXT), (2, new_text)):
            connection.execute(
                "INSERT INTO invoice_fields (id, invoice_id, code, line_no, value, source)"
                " VALUES (gen_random_uuid(), %s, 'BT-153', %s, %s, 'xml')",
                (invoice_id, line_no, text),
            )
    yield invoice_id, new_text
    with psycopg.connect(admin_url, autocommit=True) as connection:
        connection.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,))


async def test_lists_only_the_read_only_tools(server: MCPServer) -> None:
    async with Client(server) as client:
        tools = (await client.list_tools()).tools
    assert {tool.name for tool in tools} == {
        "get_invoice_history",
        "search_similar_invoices",
        "search_rulebook",
    }
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools)


async def test_history_of_a_supplier_newest_first_with_accounts(server: MCPServer) -> None:
    result = await call(server, "get_invoice_history", {"vat_id": IT_SERVICE})

    invoices = result["invoices"]
    assert 0 < len(invoices) <= history.MAX_INVOICES
    dates = [invoice["issue_date"] for invoice in invoices]
    assert dates == sorted(dates, reverse=True)
    assert all(invoice["source"] == "import" for invoice in invoices)
    # Imported history has lines and accounts, no totals.
    assert invoices[0]["gross_total"] is None
    assert all(line["account"] for invoice in invoices for line in invoice["lines"])


async def test_history_of_an_unknown_supplier_is_empty(server: MCPServer) -> None:
    result = await call(server, "get_invoice_history", {"vat_id": "DE111111111"})
    assert result["invoices"] == []


async def test_similar_invoices_by_vector_and_by_text(
    server: MCPServer, invoice_with_lines: tuple[str, str]
) -> None:
    invoice_id, _ = invoice_with_lines

    result = await call(server, "search_similar_invoices", {"invoice_id": invoice_id})

    assert result["methods"] == [
        {"line_no": 1, "method": "vector"},
        {"line_no": 2, "method": "text"},
    ]
    assert 0 < len(result["invoices"]) <= history.MAX_SIMILAR
    best = result["invoices"][0]["lines"][0]
    assert best["text"] == VECTOR_TEXT
    assert best["account"] == "4806"
    assert best["score"] == pytest.approx(1.0)


async def test_similar_invoices_of_an_invoice_without_lines(server: MCPServer) -> None:
    result = await call(server, "search_similar_invoices", {"invoice_id": str(uuid.uuid4())})
    assert result == {"methods": [], "invoices": []}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("The IBAN changed, how do I verify the new bank account?", "iban.md#"),
        ("Doppelzahlung derselben Rechnungsnummer", "duplicate.md#"),
        ("Which SKR03 account for toner and Kopierpapier?", "skr03-accounts.md#"),
    ],
)
async def test_rulebook_by_full_text_without_a_vector(
    server: MCPServer, query: str, expected: str
) -> None:
    result = await call(server, "search_rulebook", {"query": query})

    assert result["method"] == "text"
    assert 0 < len(result["sections"]) <= history.RULEBOOK_RESULTS
    assert result["sections"][0]["key"].startswith(expected)


async def test_rulebook_by_vector(server: MCPServer, admin_url: str) -> None:
    """The index loaded the packaged vectors; one section gets a vector equal to the query."""
    where = " WHERE source = 'kosit.md' AND anchor = 'how-to-resolve'"
    axis = [0.0] * history.DIMENSIONS
    axis[7] = 1.0
    with psycopg.connect(admin_url, autocommit=True) as connection:
        row = connection.execute("SELECT vector::text FROM rulebook_chunks" + where).fetchone()
        assert row is not None and row[0] is not None
        connection.execute("UPDATE rulebook_chunks SET vector = %s::vector" + where, (str(axis),))
    try:
        result = await call(server, "search_rulebook", {"query": "xyz", "query_vector": axis})
    finally:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute("UPDATE rulebook_chunks SET vector = %s::vector" + where, (row[0],))

    assert result["method"] == "vector"
    keys = [section["key"] for section in result["sections"]]
    assert len(keys) == history.RULEBOOK_RESULTS
    assert keys[0] == "kosit.md#how-to-resolve"
    assert result["sections"][0]["score"] == pytest.approx(1.0)


async def test_rulebook_query_without_words_finds_nothing(server: MCPServer) -> None:
    result = await call(server, "search_rulebook", {"query": "?!-"})
    assert result == {"method": "text", "sections": []}


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("get_invoice_history", {"vat_id": "de 999"}),
        ("get_invoice_history", {"vat_id": "DE999000033' OR '1'='1"}),
        ("search_similar_invoices", {"invoice_id": "not-a-uuid"}),
        ("search_rulebook", {"query": "ab"}),
        ("search_rulebook", {"query": "x" * 201}),
        ("search_rulebook", {"query": "iban", "query_vector": [0.1, 0.2]}),
    ],
)
async def test_invalid_arguments_are_refused(
    server: MCPServer, tool: str, arguments: dict[str, Any]
) -> None:
    assert await refused(server, tool, arguments)


def test_or_query_keeps_only_words() -> None:
    assert history.or_query("IBAN geändert? 'x' & | !y") == "iban | geändert | x | y"
    assert history.or_query("?!") is None


def test_transport_security_allows_only_the_given_hosts() -> None:
    settings = history.transport_security(["mcp-history:*"])
    assert settings.allowed_hosts == ["mcp-history:*"]
    assert settings.allowed_origins == []
