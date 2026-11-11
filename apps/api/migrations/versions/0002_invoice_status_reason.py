"""Add the awaiting_extraction status and invoices.status_reason.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = ("received", "processing", "ready", "blocked", "failed")
NEW_STATUSES = (*OLD_STATUSES, "awaiting_extraction")


def _status_check(statuses: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_invoices_invoice_status"), "invoices", type_="check")
    values = ", ".join(f"'{status}'" for status in statuses)
    op.create_check_constraint(
        op.f("ck_invoices_invoice_status"), "invoices", sa.text(f"status IN ({values})")
    )


def upgrade() -> None:
    _status_check(NEW_STATUSES)
    op.add_column("invoices", sa.Column("status_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    # The old schema has no place for these PDFs; `received` makes startup pick them up again.
    op.execute("UPDATE invoices SET status = 'received' WHERE status = 'awaiting_extraction'")
    op.drop_column("invoices", "status_reason")
    _status_check(OLD_STATUSES)
