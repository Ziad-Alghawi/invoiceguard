"""Add checks.message: one sentence per check result for the reviewer.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The default only fills rows that already exist; new rows always carry a message.
    op.add_column("checks", sa.Column("message", sa.Text(), nullable=False, server_default=""))
    op.alter_column("checks", "message", server_default=None)


def downgrade() -> None:
    op.drop_column("checks", "message")
