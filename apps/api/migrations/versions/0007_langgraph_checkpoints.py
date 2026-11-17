"""LangGraph checkpoint tables (ADR-015) in their own schema, created by the checkpointer's setup.

The setup creates indexes CONCURRENTLY, which cannot run inside a transaction, so it runs on an
autocommit connection of its own. It records its own steps in `checkpoint_migrations` and skips
those already done, so running it again (or after a library update) is safe.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-16 10:00:00
"""

from collections.abc import Sequence

import psycopg
from alembic import op
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "langgraph"


def upgrade() -> None:
    url = op.get_bind().engine.url.set(drivername="postgresql")
    with psycopg.connect(
        url.render_as_string(hide_password=False), autocommit=True, row_factory=dict_row
    ) as connection:
        connection.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        connection.execute(f"SET search_path TO {SCHEMA}")
        PostgresSaver(connection).setup()


def downgrade() -> None:
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
