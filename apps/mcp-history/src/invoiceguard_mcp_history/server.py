"""mcp-history: a read-only MCP server with the booking history and the rulebook for the exception
agent (R3-4b, ADR-017).

Tools: a supplier's past approved invoices with the accounts booked, the history lines most like
an invoice's lines, and the rulebook sections that answer a question. Everything returned was
written by suppliers or reviewers at some point, so the agent treats it as untrusted data; the
history holds only imported bookings and approved invoices that passed the injection scan
(migration 0013's views).

`search_rulebook` takes the question and, optionally, its vector: the api embeds the question
(it has the model key, and the cost counts against the agent's cap), so this server needs no key.
Without a vector the search is full text, as for chunks that have no vector yet.

Run with `invoiceguard-mcp-history` (streamable HTTP on port 8000, path /mcp).
"""

import hashlib
import os
import re
import unicodedata
from datetime import date
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from invoiceguard_mcp_history.db import Database

DIMENSIONS = 768
VatId = Annotated[
    str,
    Field(pattern=r"^[A-Z]{2}[0-9A-Z]{2,13}$", description="VAT ID, e.g. DE999000033"),
]
InvoiceId = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        description="The invoice's id (a UUID)",
    ),
]
Query = Annotated[str, Field(min_length=3, max_length=200, description="A question or keywords")]
QueryVector = Annotated[
    list[float] | None,
    Field(
        min_length=DIMENSIONS, max_length=DIMENSIONS, description="Set by the api, not the model"
    ),
]
READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
Method = Literal["vector", "text"]

MAX_INVOICES = 10
MAX_LINES_PER_INVOICE = 10
MAX_ITEM_LINES = 20
MATCHES_PER_LINE = 5
MAX_SIMILAR = 5
RULEBOOK_RESULTS = 3
# Item names longer than this are cut before hashing, as in the api (booking/text.py).
MAX_TEXT_CHARS = 500
_WORD = re.compile(r"[^\W_]+")


def normalise(text: str) -> str:
    """A copy of `invoiceguard_api.booking.text.normalise`, so a line's hash finds its vector:
    NFC with whitespace collapsed, cut to MAX_TEXT_CHARS. A test in packages/evals compares the
    two."""
    return " ".join(unicodedata.normalize("NFC", text).split())[:MAX_TEXT_CHARS]


def text_sha256(normalised: str) -> str:
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def or_query(query: str) -> str | None:
    """The words of the question joined by OR, for `to_tsquery`: a question matches a section
    that shares some of its words, not only one that has all. Only letters and digits reach the
    query syntax."""
    words = list(dict.fromkeys(word.casefold() for word in _WORD.findall(query)))
    return " | ".join(words) or None


class HistoryLine(BaseModel):
    line_no: int
    text: str
    account: str


class HistoryInvoice(BaseModel):
    invoice_number: str | None
    issue_date: date | None
    supplier_name: str | None
    # `import`: booking history brought from the old system; `invoice`: approved here.
    source: str
    # Null for imported history (it has the lines and accounts only).
    currency: str | None
    net_total: str | None
    gross_total: str | None
    payee_iban: str | None
    lines: list[HistoryLine]


class InvoiceHistory(BaseModel):
    vat_id: str
    invoices: list[HistoryInvoice]


class SimilarLine(BaseModel):
    # The line of the investigated invoice this history line is like.
    for_line_no: int
    text: str
    account: str
    score: float


class SimilarInvoice(BaseModel):
    invoice_number: str | None
    issue_date: date | None
    supplier_name: str | None
    supplier_vat_id: str | None
    lines: list[SimilarLine]


class LineMethod(BaseModel):
    # A line of the investigated invoice, searched by vector or, without one, by text match.
    line_no: int
    method: Method


class SimilarInvoices(BaseModel):
    # No id of the investigated invoice: what the agent reads stays the same across runs.
    methods: list[LineMethod]
    invoices: list[SimilarInvoice]


class RulebookSection(BaseModel):
    # `iban.md#how-to-resolve-a-changed-iban`
    key: str
    title: str
    heading: str
    text: str
    score: float


class RulebookResults(BaseModel):
    method: Method
    sections: list[RulebookSection]


HISTORY_SQL = """
SELECT h.invoice_id, h.source, h.invoice_number, h.issue_date, h.supplier_name, h.line_no,
       h.text, h.account, i.currency, i.net_total, i.gross_total, i.payee_iban
FROM history_lines h
LEFT JOIN history_invoices i ON i.invoice_id = h.invoice_id
WHERE h.supplier_vat_id = %(vat_id)s
ORDER BY h.issue_date DESC NULLS LAST, h.invoice_number, h.line_no
LIMIT 500
"""
ITEM_NAMES_SQL = """
SELECT line_no, item_name FROM invoice_item_names
WHERE invoice_id = %(invoice_id)s
ORDER BY line_no
LIMIT %(limit)s
"""
HAS_VECTOR_SQL = "SELECT 1 FROM embeddings WHERE model = %(model)s AND text_sha256 = %(sha)s"
_MATCH_COLUMNS = """h.invoice_id, h.invoice_number, h.issue_date, h.supplier_name,
       h.supplier_vat_id, h.text, h.account"""
VECTOR_MATCH_SQL = f"""
SELECT {_MATCH_COLUMNS}, 1 - (e.vector <=> q.vector) AS score
FROM history_lines h
JOIN embeddings e ON e.model = %(model)s AND e.text_sha256 = h.text_sha256
CROSS JOIN (SELECT vector FROM embeddings WHERE model = %(model)s AND text_sha256 = %(sha)s) q
WHERE h.invoice_id IS DISTINCT FROM %(invoice_id)s::uuid
ORDER BY score DESC, h.invoice_number, h.line_no
LIMIT %(k)s
"""
TEXT_MATCH_SQL = f"""
SELECT {_MATCH_COLUMNS}, similarity(h.text, %(text)s) AS score
FROM history_lines h
WHERE h.invoice_id IS DISTINCT FROM %(invoice_id)s::uuid AND similarity(h.text, %(text)s) > 0
ORDER BY score DESC, h.invoice_number, h.line_no
LIMIT %(k)s
"""
RULEBOOK_VECTOR_SQL = """
SELECT source, anchor, title, heading, text, 1 - (vector <=> %(vector)s::vector) AS score
FROM rulebook_chunks
WHERE model = %(model)s AND vector IS NOT NULL
ORDER BY score DESC, id
LIMIT %(k)s
"""
# Both stemmers, as the tsv column (migration 0013); rank divided by 1 + log(length).
RULEBOOK_TEXT_SQL = """
SELECT source, anchor, title, heading, text, ts_rank(tsv, q, 1) AS score
FROM rulebook_chunks,
     (SELECT to_tsquery('english', %(words)s) || to_tsquery('german', %(words)s) AS q) query
WHERE tsv @@ q
ORDER BY score DESC, id
LIMIT %(k)s
"""


def _history(rows: list[dict[str, Any]]) -> list[HistoryInvoice]:
    invoices: dict[tuple[Any, ...], HistoryInvoice] = {}
    for row in rows:
        key = (row["invoice_id"], row["invoice_number"], row["issue_date"])
        invoice = invoices.get(key)
        if invoice is None:
            if len(invoices) == MAX_INVOICES:
                continue
            invoice = invoices[key] = HistoryInvoice(
                lines=[],
                **{name: row[name] for name in HistoryInvoice.model_fields if name != "lines"},
            )
        if len(invoice.lines) < MAX_LINES_PER_INVOICE:
            invoice.lines.append(HistoryLine.model_validate(row))
    return list(invoices.values())


def _similar(found: list[tuple[int, dict[str, Any]]]) -> list[SimilarInvoice]:
    """History lines grouped by their invoice, the invoice with the best match first."""
    groups: dict[tuple[Any, ...], tuple[float, SimilarInvoice]] = {}
    for line_no, row in found:
        key = (row["invoice_id"], row["invoice_number"], row["issue_date"])
        score = round(float(row["score"]), 4)
        best, invoice = groups.get(key, (score, None))
        if invoice is None:
            invoice = SimilarInvoice(
                lines=[],
                **{name: row[name] for name in SimilarInvoice.model_fields if name != "lines"},
            )
        invoice.lines.append(
            SimilarLine(for_line_no=line_no, text=row["text"], account=row["account"], score=score)
        )
        groups[key] = (max(best, score), invoice)
    ranked = sorted(groups.values(), key=lambda entry: -entry[0])
    return [invoice for _, invoice in ranked[:MAX_SIMILAR]]


def build_server(database: Database, embedding_model: str) -> MCPServer:
    server = MCPServer(
        name="invoiceguard-mcp-history",
        instructions="Read-only booking history of approved invoices, and the AP rulebook.",
        version="0.1.0",
    )

    @server.tool(annotations=READ_ONLY)
    def get_invoice_history(vat_id: VatId) -> InvoiceHistory:
        """A supplier's past approved invoices, newest first, with the lines and the accounts
        booked; totals and payee IBAN for invoices approved in this system."""
        rows = database.rows(HISTORY_SQL, {"vat_id": vat_id})
        return InvoiceHistory(vat_id=vat_id, invoices=_history(rows))

    @server.tool(annotations=READ_ONLY)
    def search_similar_invoices(invoice_id: InvoiceId) -> SimilarInvoices:
        """Past approved invoices with lines like this invoice's lines, by vector or by text
        match, with the accounts booked."""
        items = database.rows(ITEM_NAMES_SQL, {"invoice_id": invoice_id, "limit": MAX_ITEM_LINES})
        methods: list[LineMethod] = []
        found: list[tuple[int, dict[str, Any]]] = []
        for item in items:
            text = normalise(item["item_name"])
            sha = text_sha256(text)
            params = {"invoice_id": invoice_id, "k": MATCHES_PER_LINE}
            if database.rows(HAS_VECTOR_SQL, {"model": embedding_model, "sha": sha}):
                method: Method = "vector"
                rows = database.rows(
                    VECTOR_MATCH_SQL, {**params, "model": embedding_model, "sha": sha}
                )
            else:
                method = "text"
                rows = database.rows(TEXT_MATCH_SQL, {**params, "text": text})
            methods.append(LineMethod(line_no=item["line_no"], method=method))
            found.extend((item["line_no"], row) for row in rows)
        return SimilarInvoices(methods=methods, invoices=_similar(found))

    @server.tool(annotations=READ_ONLY)
    def search_rulebook(query: Query, query_vector: QueryVector = None) -> RulebookResults:
        """The rulebook sections (what a check means, thresholds, how to resolve it, SKR03
        accounts) that best answer the question."""
        method: Method
        if query_vector is not None:
            rows = database.rows(
                RULEBOOK_VECTOR_SQL,
                {"vector": str(query_vector), "model": embedding_model, "k": RULEBOOK_RESULTS},
            )
            method = "vector"
        else:
            words = or_query(query)
            rows = (
                []
                if words is None
                else database.rows(RULEBOOK_TEXT_SQL, {"words": words, "k": RULEBOOK_RESULTS})
            )
            method = "text"
        return RulebookResults(
            method=method,
            sections=[
                RulebookSection(
                    key=f"{row['source']}#{row['anchor']}",
                    title=row["title"],
                    heading=row["heading"],
                    text=row["text"],
                    score=round(float(row["score"]), 4),
                )
                for row in rows
            ],
        )

    return server


def transport_security(allowed_hosts: list[str]) -> TransportSecuritySettings:
    """Only these Host headers are served (DNS rebinding protection); no browser origin."""
    return TransportSecuritySettings(allowed_hosts=allowed_hosts, allowed_origins=[])


def main() -> None:
    database = Database(os.environ["INVOICEGUARD_MCP_HISTORY_DATABASE_URL"])
    model = os.environ.get("INVOICEGUARD_EMBEDDING_MODEL") or "gemini/gemini-embedding-001"
    hosts = os.environ.get(
        "INVOICEGUARD_MCP_ALLOWED_HOSTS", "mcp-history:*,localhost:*,127.0.0.1:*"
    )
    build_server(database, model).run(
        "streamable-http",
        # All interfaces inside the container; Compose decides who can reach the port.
        host="0.0.0.0",
        port=int(os.environ.get("INVOICEGUARD_MCP_PORT", "8000")),
        stateless_http=True,
        json_response=True,
        transport_security=transport_security(hosts.split(",")),
    )
