"""Booking suggestions (R3-4, ADR-020): the accounts booked per invoice line, and embedding
vectors per text in pgvector.

Both extensions ship with the pgvector/pgvector:pg16 image: `vector` for the vectors, `pg_trgm`
for the text match used when a line has no vector. Creating them needs a user that may create
extensions (the Compose superuser; in Kubernetes the migration Job's user). The search is an
exact scan, so there is no vector or trigram index yet (ADR-020).

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-19 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "embeddings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("vector", Vector(768), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_embeddings")),
        sa.UniqueConstraint("model", "text_sha256", name=op.f("uq_embeddings_model_text_sha256")),
    )
    op.create_table(
        "bookings",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "source",
            sa.Enum(
                "invoice",
                "import",
                name="booking_source",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("supplier_vat_id", sa.String(length=20), nullable=True),
        sa.Column("supplier_name", sa.Text(), nullable=True),
        sa.Column("invoice_number", sa.String(length=100), nullable=True),
        sa.Column("issue_date", sa.Date(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        sa.Column("account", sa.String(length=8), nullable=False),
        sa.Column("suggested_account", sa.String(length=8), nullable=True),
        sa.Column("searchable", sa.Boolean(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_bookings_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_bookings_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookings")),
        sa.UniqueConstraint("invoice_id", "line_no", name=op.f("uq_bookings_invoice_id_line_no")),
    )
    op.create_index("ix_bookings_text_sha256", "bookings", ["text_sha256"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_bookings_text_sha256", table_name="bookings")
    op.drop_table("bookings")
    op.drop_table("embeddings")
    # The extensions stay: other objects in the database may use them, and they hold no data.
