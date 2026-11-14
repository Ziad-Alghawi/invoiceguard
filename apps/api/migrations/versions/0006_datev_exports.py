"""DATEV-style export (ADR-013): datev_exports and the export an invoice is in.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-14 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "datev_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_count", sa.Integer(), nullable=False),
        sa.Column("fiscal_year_start", sa.Date(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("filename", sa.String(length=100), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_datev_exports_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_datev_exports")),
    )
    op.add_column("invoices", sa.Column("datev_export_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_invoices_datev_export_id_datev_exports"),
        "invoices",
        "datev_exports",
        ["datev_export_id"],
        ["id"],
    )
    op.create_index("ix_invoices_datev_export_id", "invoices", ["datev_export_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_invoices_datev_export_id", table_name="invoices")
    op.drop_constraint(
        op.f("fk_invoices_datev_export_id_datev_exports"), "invoices", type_="foreignkey"
    )
    op.drop_column("invoices", "datev_export_id")
    op.drop_table("datev_exports")
