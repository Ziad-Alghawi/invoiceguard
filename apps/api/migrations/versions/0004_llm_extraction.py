"""LLM extraction (ADR-010): invoice_fields.evidence and the model_calls cost log (ADR-004).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-12 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "invoice_fields",
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_table(
        "model_calls",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "ok",
                "invalid_output",
                "price_unknown",
                "error",
                name="model_call_status",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_model_calls_invoice_id_invoices"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_calls")),
    )
    op.create_index("ix_model_calls_invoice_id", "model_calls", ["invoice_id"], unique=False)
    op.create_index("ix_model_calls_at", "model_calls", ["at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_model_calls_at", table_name="model_calls")
    op.drop_index("ix_model_calls_invoice_id", table_name="model_calls")
    op.drop_table("model_calls")
    op.drop_column("invoice_fields", "evidence")
