"""Read-only MCP servers (R2-5, ADR-017): goods receipts, a supplier contact email, and one
PostgreSQL role per MCP server with SELECT on its own tables only.

Roles belong to the whole PostgreSQL server, not to one database, so they are created only when
missing (the dev and test databases share a server) and the downgrade revokes their grants but
keeps them. They are created without LOGIN; `invoiceguard-db-roles` gives them a password from
the environment (db_roles.py), so no secret is in a migration.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-18 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ERP_ROLE = "invoiceguard_mcp_erp"
REGISTRY_ROLE = "invoiceguard_mcp_registry"
# mcp-erp: supplier master data, purchase orders and goods receipts.
ERP_TABLES = (
    "suppliers",
    "purchase_orders",
    "purchase_order_lines",
    "goods_receipts",
    "goods_receipt_lines",
)
# mcp-registry: who a supplier is and its bank accounts; not the address or contact.
REGISTRY_SUPPLIER_COLUMNS = ("id", "name", "vat_id", "country_code")
REGISTRY_TABLES = ("supplier_bank_accounts",)


def _create_role(role: str) -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                CREATE ROLE {role} NOLOGIN;
            END IF;
        END
        $$
        """
    )


def upgrade() -> None:
    op.add_column("suppliers", sa.Column("contact_email", sa.String(length=255), nullable=True))
    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=50), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_orders.id"],
            name=op.f("fk_goods_receipts_purchase_order_id_purchase_orders"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goods_receipts")),
        sa.UniqueConstraint("number", name=op.f("uq_goods_receipts_number")),
    )
    op.create_index("ix_goods_receipts_purchase_order_id", "goods_receipts", ["purchase_order_id"])
    op.create_table(
        "goods_receipt_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("goods_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("po_line_no", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.ForeignKeyConstraint(
            ["goods_receipt_id"],
            ["goods_receipts.id"],
            name=op.f("fk_goods_receipt_lines_goods_receipt_id_goods_receipts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goods_receipt_lines")),
        sa.UniqueConstraint(
            "goods_receipt_id",
            "po_line_no",
            name=op.f("uq_goods_receipt_lines_goods_receipt_id_po_line_no"),
        ),
    )

    _create_role(ERP_ROLE)
    _create_role(REGISTRY_ROLE)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ERP_ROLE}, {REGISTRY_ROLE}")
    op.execute(f"GRANT SELECT ON {', '.join(ERP_TABLES)} TO {ERP_ROLE}")
    op.execute(
        f"GRANT SELECT ({', '.join(REGISTRY_SUPPLIER_COLUMNS)}) ON suppliers TO {REGISTRY_ROLE}"
    )
    op.execute(f"GRANT SELECT ON {', '.join(REGISTRY_TABLES)} TO {REGISTRY_ROLE}")


def downgrade() -> None:
    # Column grants go with REVOKE ALL on the table; the roles stay (see the module docstring).
    op.execute(f"REVOKE ALL ON {', '.join(ERP_TABLES)} FROM {ERP_ROLE}")
    op.execute(f"REVOKE ALL ON suppliers, {', '.join(REGISTRY_TABLES)} FROM {REGISTRY_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {ERP_ROLE}, {REGISTRY_ROLE}")
    op.drop_table("goods_receipt_lines")
    op.drop_index("ix_goods_receipts_purchase_order_id", table_name="goods_receipts")
    op.drop_table("goods_receipts")
    op.drop_column("suppliers", "contact_email")
