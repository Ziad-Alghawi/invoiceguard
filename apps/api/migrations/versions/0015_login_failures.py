"""Failed logins per client address for the per-IP login limit (R4-2, ADR-011).

Not append-only: the api deletes rows older than the limit's window, so the addresses are kept
for minutes only. The api's role gets its data rights through the default privileges of
migration 0014.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-19 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_failures",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("client_ip", sa.String(length=64), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_failures")),
    )
    op.create_index("ix_login_failures_client_ip_at", "login_failures", ["client_ip", "at"])


def downgrade() -> None:
    op.drop_index("ix_login_failures_client_ip_at", table_name="login_failures")
    op.drop_table("login_failures")
