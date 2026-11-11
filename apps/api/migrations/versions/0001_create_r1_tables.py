"""Create the R1 tables: invoices, fields, checks, suppliers, bank accounts, orders, audit.

Revision ID: 0001
Revises:
Create Date: 2026-11-11 23:09:25.512777
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=50), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(
        "ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"], unique=False
    )
    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "received",
                "processing",
                "ready",
                "blocked",
                "failed",
                name="invoice_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "source_type",
            sa.Enum(
                "xml",
                "pdf",
                name="source_type",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_path", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.UniqueConstraint("sha256", name=op.f("uq_invoices_sha256")),
    )
    op.create_index("ix_invoices_created_at", "invoices", ["created_at"], unique=False)
    op.create_table(
        "suppliers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("vat_id", sa.String(length=20), nullable=False),
        sa.Column("street", sa.String(length=255), nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppliers")),
        sa.UniqueConstraint("vat_id", name=op.f("uq_suppliers_vat_id")),
    )
    op.create_table(
        "checks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "passed",
                "warning",
                "failed",
                "skipped",
                name="check_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_checks_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checks")),
    )
    op.create_index("ix_checks_invoice_id", "checks", ["invoice_id"], unique=False)
    op.create_table(
        "invoice_fields",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "xml",
                "llm",
                name="field_source",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_invoice_fields_confidence_range")
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_invoice_fields_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_fields")),
        sa.UniqueConstraint(
            "invoice_id",
            "code",
            "line_no",
            name=op.f("uq_invoice_fields_invoice_id_code_line_no"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=50), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["suppliers.id"], name=op.f("fk_purchase_orders_supplier_id_suppliers")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_orders")),
        sa.UniqueConstraint("number", name=op.f("uq_purchase_orders_number")),
    )
    op.create_table(
        "supplier_bank_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("iban", sa.String(length=34), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("since", sa.Date(), nullable=False),
        sa.Column("verified_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name=op.f("fk_supplier_bank_accounts_supplier_id_suppliers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_bank_accounts")),
        sa.UniqueConstraint(
            "supplier_id", "iban", name=op.f("uq_supplier_bank_accounts_supplier_id_iban")
        ),
    )
    op.create_table(
        "purchase_order_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("unit_code", sa.String(length=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("vat_rate", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_orders.id"],
            name=op.f("fk_purchase_order_lines_purchase_order_id_purchase_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_order_lines")),
        sa.UniqueConstraint(
            "purchase_order_id",
            "line_no",
            name=op.f("uq_purchase_order_lines_purchase_order_id_line_no"),
        ),
    )


def downgrade() -> None:
    op.drop_table("purchase_order_lines")
    op.drop_table("supplier_bank_accounts")
    op.drop_table("purchase_orders")
    op.drop_table("invoice_fields")
    op.drop_index("ix_checks_invoice_id", table_name="checks")
    op.drop_table("checks")
    op.drop_table("suppliers")
    op.drop_index("ix_invoices_created_at", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_table("audit_events")
