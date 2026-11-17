"""Four-eyes override (ADR-016): user roles and the status `override_requested`.

Existing users become reviewers; `make seed-user` sets the role of the users it seeds.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-17 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = (
    "received",
    "processing",
    "awaiting_extraction",
    "ready",
    "blocked",
    "failed",
    "approved",
    "rejected",
)
NEW_STATUSES = (*OLD_STATUSES, "override_requested")


def _status_check(statuses: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_invoices_invoice_status"), "invoices", type_="check")
    values = ", ".join(f"'{status}'" for status in statuses)
    op.create_check_constraint(
        op.f("ck_invoices_invoice_status"), "invoices", sa.text(f"status IN ({values})")
    )


def upgrade() -> None:
    _status_check(NEW_STATUSES)
    # The server default fills the existing rows; the model sets the role of new ones.
    op.add_column(
        "users",
        sa.Column(
            "role",
            sa.Enum("reviewer", "approver", name="user_role", native_enum=False, length=20),
            nullable=False,
            server_default="reviewer",
        ),
    )
    op.alter_column("users", "role", server_default=None)
    op.create_check_constraint(
        op.f("ck_users_user_role"), "users", sa.text("role IN ('reviewer', 'approver')")
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_user_role"), "users", type_="check")
    op.drop_column("users", "role")
    # The old schema has no pending override: back to blocked, which the audit log explains.
    op.execute("UPDATE invoices SET status = 'blocked' WHERE status = 'override_requested'")
    _status_check(OLD_STATUSES)
