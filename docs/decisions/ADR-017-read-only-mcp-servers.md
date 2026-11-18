# ADR-017: Read-only MCP servers with one database role each

- **Status:** Accepted
- **Date:** 2026-11-18

## Context

The exception agent (R2-6, ADR-018) investigates blocked invoices: it needs the supplier's master data, the
purchase order with what was delivered, and the supplier's verified bank accounts. In a real company these live
in other systems (ERP, a vendor or bank-details registry), owned by other teams, reached over an interface.

The agent reads untrusted invoice text, so it must be assumed that it can be steered (OWASP Agentic ASI01). What
it can reach is therefore the real safety boundary (ASI02 tool misuse, ASI03 privilege): its tools must not be
able to write anything or read data they do not need, whatever the model asks for. PLAN §3 rules out any tool that
pays, posts or writes to an ERP or registry.

Today all data is in one PostgreSQL database, read by the api with its owner account.

## Decision

Two **MCP servers**, `apps/mcp-erp` and `apps/mcp-registry`, each its own small uv project and Compose service,
built with the official MCP Python SDK (`mcp` 2.3.0, `MCPServer`) and served over **streamable HTTP**
(stateless, JSON responses, path `/mcp`).

**Tools: small, typed, read-only.**

- `mcp-erp`: `get_supplier(vat_id)`, `list_purchase_orders(vat_id)`, `get_purchase_order(number)` (lines with the
  quantity received so far), `get_goods_receipts(po_number)`.
- `mcp-registry`: `check_vat_id(vat_id)` (German check digit, known supplier), `check_iban(iban)` (checksum, which
  suppliers have it), `get_bank_accounts(vat_id)` (verified or not, since when, by whom).
- Every input has a pattern (VAT ID, IBAN, order number) checked before any query; every output is a Pydantic
  model, so `tools/list` carries an output schema. Lists are bounded (at most 20 orders).
- Fixed, parameterised SQL. No tool takes SQL, a table name or a filter expression.
- Tools are annotated `readOnlyHint`; that is a hint for clients, not the guarantee. The guarantee is the role.

**One PostgreSQL role per server (least privilege).** Migration 0010 creates `invoiceguard_mcp_erp` and
`invoiceguard_mcp_registry` and grants `SELECT` only:

| Role | May read |
| --- | --- |
| `invoiceguard_mcp_erp` | `suppliers`, `purchase_orders`, `purchase_order_lines`, `goods_receipts`, `goods_receipt_lines` |
| `invoiceguard_mcp_registry` | `supplier_bank_accounts`; of `suppliers` only `id`, `name`, `vat_id`, `country_code` (column grant) |

Nothing else: no `invoices`, `users`, `sessions`, `audit_events`, `model_calls`, no `langgraph` schema, no
`INSERT`/`UPDATE`/`DELETE`/`TRUNCATE`, no `CREATE`. The ERP server cannot see bank accounts, the registry server
cannot see orders or contact data. As a second guard, every transaction the servers open is `READ ONLY`.

- **Roles are server-wide in PostgreSQL**, so the migration creates them only if they are missing (the dev and test
  databases share one server), and its downgrade revokes the grants but keeps the roles.
- **No secret in a migration.** The roles are created `NOLOGIN`. `invoiceguard-db-roles` runs after
  `alembic upgrade head` when the api starts and sets `LOGIN PASSWORD` from `INVOICEGUARD_MCP_ERP_DB_PASSWORD` and
  `INVOICEGUARD_MCP_REGISTRY_DB_PASSWORD`; an empty variable makes the role `NOLOGIN` again. This also works on the
  existing dev and demo volumes, where an init script in `docker-entrypoint-initdb.d` would never run. Compose
  refuses to start without both passwords. The schema (and the grants) stay owned by the api's migrations.
- **Tests** run as the roles without touching their passwords (another database on the same server uses them):
  the api's role tests use `SET LOCAL ROLE` in a rolled-back transaction; the servers' tests connect with the test
  admin user and `-c role=...`. Both get exactly the role's privileges.

**Network.** The servers listen only on the Compose network; dev publishes them on `127.0.0.1` (8091, 8092) for
debugging, the prod override removes the ports. The SDK's DNS rebinding protection accepts only the Host headers in
`INVOICEGUARD_MCP_ALLOWED_HOSTS` (default: the service name and loopback) and no browser origin. There is no
application-level authentication between the api and the servers: they are reachable only from inside the stack,
and what they return is master data the agent may read anyway; the protection that matters is that they cannot
write.

**Data.** New tables `goods_receipts` and `goods_receipt_lines` (mock ERP deliveries) and `suppliers.contact_email`
(where supplier emails go, ADR-018). The demo seed gives the blocked samples real findings: the IBAN of sample 02 is
registered to no supplier; sample 03's order was delivered but at a lower price than invoiced; some orders are not
or only partly delivered.

`get_invoice_history` (PLAN §5) is **not** built: it would give the ERP role access to `invoices`, which holds
untrusted documents and is app data, not ERP data. It returns in R3 together with `search_similar_invoices`, over
a read model of approved invoices only.

## Alternatives

- **Python functions inside the api instead of MCP:** simpler, but the tools would run with the api's database owner
  account, so a bug in one tool could write anything. Separate processes with separate roles make the boundary
  structural, and MCP is the standard interface agent tooling expects.
- **One MCP server for both:** fewer containers, but one role with the union of both grants; the registry (bank
  details) is exactly the data an ERP integration should not need.
- **Row-level security or views instead of table grants:** finer control, more moving parts; the split here follows
  whole tables (plus one column grant), which plain grants express clearly.
- **Roles and passwords in an init script:** runs only on an empty volume, so existing databases would never get
  them; passwords in a migration would put secrets into the repository's history.
- **stdio transport:** each server would run as a child process of the api, sharing its container and its
  environment (with the owner's database URL); HTTP keeps them separate services.
- **Shared token between api and servers:** adds a secret to manage for little gain while the servers are reachable
  only inside the stack and read-only; reconsider when they move to Kubernetes (R4, network policies).

## Consequences

- A steered agent can at most read the master data of these tables; there is no tool or privilege to write.
  Tests prove for each role that other tables and columns are refused and that writes fail.
- The migration needs a database user that may create roles (the Compose `POSTGRES_USER` is a superuser). A
  production setup with a restricted migration user (R4 backlog) must create the roles beforehand.
- Two more containers (about 60 MB of memory each) and two more `.env` secrets; the demo server's `.env` needs them
  before `make prod-up` (`docs/deploy.md`).
- The servers' tests build their own database with the api's migrations and seed, so `make test` and CI install the
  api project for them; the schema has one owner.
- One database connection per tool call: fine for a handful of calls per invoice, a pool would be needed for load.
- New dependency `mcp` 2.3.0 (named in the stack, ADR-001), released on 2026-10-02. The api adds it in R2-6 for the
  client side.
