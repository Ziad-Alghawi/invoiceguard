# apps/mcp-history

Read-only MCP server with the booking history and the rulebook for the exception agent (R3-4b,
[ADR-017](../../docs/decisions/ADR-017-read-only-mcp-servers.md), [ADR-020](../../docs/decisions/ADR-020-booking-suggestions-pgvector.md)).
Streamable HTTP at `http://mcp-history:8000/mcp` on the Compose network.

| Tool | Input | Returns |
| --- | --- | --- |
| `get_invoice_history` | `vat_id` | Up to 10 past invoices of the supplier, newest first: lines, accounts booked, and totals and payee IBAN for invoices approved here |
| `search_similar_invoices` | `invoice_id` | Up to 5 past invoices with lines like the invoice's lines, by vector or by text match, with the accounts booked |
| `search_rulebook` | `query`, `query_vector` (set by the api) | The 3 rulebook sections ([docs/rulebook](../../docs/rulebook)) that best answer the question, by vector or by full text |

- Logs in as the PostgreSQL role `invoiceguard_mcp_history`, which may only `SELECT` the views `history_lines`,
  `history_invoices` and `invoice_item_names`, the table `rulebook_chunks`, and the columns `model`, `text_sha256`
  and `vector` of `embeddings` (migration 0013 in `apps/api`). It cannot read `invoices`, `invoice_fields`,
  `bookings` or any line text through `embeddings`. Every transaction is also `READ ONLY`. No tool writes, and no
  tool takes SQL.
- The history is imported bookings and approved invoices that did not fail the prompt-injection check; their text
  is still untrusted data for the agent.
- No model key: the api embeds the rulebook question and passes the vector; without one the search is full text
  (English and German stemmers, words joined by OR).
- `normalise` is a copy of the api's (`booking/text.py`); `packages/evals/tests` checks that they agree.
- Configuration: `INVOICEGUARD_MCP_HISTORY_DATABASE_URL`, `INVOICEGUARD_EMBEDDING_MODEL` (default
  `gemini/gemini-embedding-001`), `INVOICEGUARD_MCP_ALLOWED_HOSTS` (default `mcp-history:*,localhost:*,127.0.0.1:*`).

Tests (`uv run pytest`) need `INVOICEGUARD_TEST_DATABASE_URL`, as for `apps/mcp-erp`.
