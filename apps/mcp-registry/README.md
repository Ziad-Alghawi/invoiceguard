# apps/mcp-registry

Read-only MCP server with supplier registry checks for the exception agent (R2-5, [ADR-017](../../docs/decisions/ADR-017-read-only-mcp-servers.md)).
Streamable HTTP at `http://mcp-registry:8000/mcp` on the Compose network.

| Tool | Input | Returns |
| --- | --- | --- |
| `check_vat_id` | `vat_id` | Check digit (German IDs) and the known supplier, if any |
| `check_iban` | `iban` | IBAN checksum and the suppliers it is registered to |
| `get_bank_accounts` | `vat_id` | The supplier's accounts: verified or not, since when, by whom |

- Logs in as the PostgreSQL role `invoiceguard_mcp_registry`, which may only `SELECT` `supplier_bank_accounts` and the
  columns `id`, `name`, `vat_id`, `country_code` of `suppliers` (migration 0010 in `apps/api`). Every transaction is
  also `READ ONLY`. No tool writes, and no tool takes SQL.
- Checksums are computed locally; there is no call to VIES or a bank.
- Configuration: `INVOICEGUARD_MCP_REGISTRY_DATABASE_URL`, `INVOICEGUARD_MCP_ALLOWED_HOSTS` (default
  `mcp-registry:*,localhost:*,127.0.0.1:*`).

Tests (`uv run pytest`) need `INVOICEGUARD_TEST_DATABASE_URL`, as for `apps/mcp-erp`.
