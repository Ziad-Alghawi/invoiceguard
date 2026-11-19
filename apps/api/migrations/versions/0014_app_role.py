"""The api's restricted database role (R4-2, ADR-022): data rights only.

`invoiceguard_app` may read and write rows, but it owns nothing, so it cannot drop or disable
the append-only triggers, alter or drop tables, or TRUNCATE (never granted). On the three
append-only logs it may only read and insert; the triggers stay as a second layer. Migrations
and other owner tasks (`invoiceguard-db-roles`, the demo reset) run as the owner in the
`migrate` step, never in the api.

Like the MCP roles (migration 0010) the role belongs to the whole server, is created only when
missing and without LOGIN; `invoiceguard-db-roles` gives it its password from the environment.
Default privileges give it the same data rights on tables that later migrations create; a
later append-only table must revoke UPDATE and DELETE again.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-19 20:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "invoiceguard_app"
SCHEMAS = ("public", "langgraph")
DML = "SELECT, INSERT, UPDATE, DELETE"
# Read and write.
TABLES = (
    "agent_runs",
    "agent_steps",
    "bookings",
    "checks",
    "datev_exports",
    "embeddings",
    "goods_receipt_lines",
    "goods_receipts",
    "invoice_fields",
    "invoices",
    "purchase_order_lines",
    "purchase_orders",
    "rulebook_chunks",
    "sessions",
    "supplier_bank_accounts",
    "suppliers",
    "users",
    "langgraph.checkpoint_blobs",
    "langgraph.checkpoint_writes",
    "langgraph.checkpoints",
)
# Append-only logs: read and insert.
APPEND_ONLY = ("audit_events", "security_events", "model_calls")
# Read only: the migration bookkeeping and the history views (migration 0013).
READ_ONLY = (
    "alembic_version",
    "langgraph.checkpoint_migrations",
    "history_lines",
    "history_invoices",
    "invoice_item_names",
)


def upgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN;
            END IF;
        END
        $$
        """
    )
    # PostgreSQL 15 and later default to this; stated so it holds on any server.
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    for schema in SCHEMAS:
        op.execute(f"GRANT USAGE ON SCHEMA {schema} TO {APP_ROLE}")
        op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} TO {APP_ROLE}")
        # Tables the owner (the role running migrations) creates later.
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT {DML} ON TABLES TO {APP_ROLE}"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
        )
    op.execute(f"GRANT {DML} ON {', '.join(TABLES)} TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON {', '.join(APPEND_ONLY)} TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON {', '.join(READ_ONLY)} TO {APP_ROLE}")


def downgrade() -> None:
    # The role stays (other databases on the server may use it); its rights here go.
    for schema in SCHEMAS:
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON TABLES FROM {APP_ROLE}"
        )
        op.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} REVOKE ALL ON SEQUENCES FROM {APP_ROLE}"
        )
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {schema} FROM {APP_ROLE}")
        op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {schema} FROM {APP_ROLE}")
        op.execute(f"REVOKE USAGE ON SCHEMA {schema} FROM {APP_ROLE}")
