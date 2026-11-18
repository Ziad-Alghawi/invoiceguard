# apps/mcp-erp

Read-only MCP server with mock ERP data for the exception agent (R2-5, [ADR-017](../../docs/decisions/ADR-017-read-only-mcp-servers.md)).
Streamable HTTP at `http://mcp-erp:8000/mcp` on the Compose network.

| Tool | Input | Returns |
| --- | --- | --- |
| `get_supplier` | `vat_id` | Master data: name, address, contact email |
| `list_purchase_orders` | `vat_id` | The supplier's orders, newest first (at most 20), with net amounts |
| `get_purchase_order` | `number` | Order lines with the quantity received so far |
| `get_goods_receipts` | `po_number` | Deliveries booked against the order |

- Logs in as the PostgreSQL role `invoiceguard_mcp_erp`, which may only `SELECT` from `suppliers`, `purchase_orders`,
  `purchase_order_lines`, `goods_receipts` and `goods_receipt_lines` (migration 0010 in `apps/api`). Every
  transaction is also `READ ONLY`. No tool writes, and no tool takes SQL.
- Inputs are checked against patterns before any query; outputs are typed (JSON schema in `tools/list`).
- Configuration: `INVOICEGUARD_MCP_ERP_DATABASE_URL` (libpq URL with the role and its password),
  `INVOICEGUARD_MCP_ALLOWED_HOSTS` (Host headers served, default `mcp-erp:*,localhost:*,127.0.0.1:*`).

Tests (`uv run pytest`) need `INVOICEGUARD_TEST_DATABASE_URL`: they create their own database with the api's
migrations and demo seed and run as the role.
