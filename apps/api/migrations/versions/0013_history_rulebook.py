"""History and rulebook for the agent (R3-4b, ADR-017, ADR-020): the rulebook's chunks with their
vectors and full-text index, a read model of the booking history as views, and the role of the
`mcp-history` server, which may read those views and nothing else of the invoices.

The views are the read model. `history_lines` holds searchable bookings of imported history and
of approved invoices that did not fail the prompt-injection check; `history_invoices` adds the
totals and payee IBAN of those approved invoices; `invoice_item_names` gives the item names of any
invoice, so the server can find the vectors of the invoice being investigated (it never returns
those names). A view runs with its owner's privileges, so the role needs no grant on `bookings`,
`invoices`, `invoice_fields` or `checks`. `security_barrier` keeps a function in a query from
seeing the rows a view filters out.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-19 18:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HISTORY_ROLE = "invoiceguard_mcp_history"
VIEWS = ("history_lines", "history_invoices", "invoice_item_names")
# The embeddings' text is any invoice's line text; the role needs only the vectors.
EMBEDDING_COLUMNS = ("model", "text_sha256", "vector")
# Both stemmers: the rulebook is English with German terms, questions come in both languages.
TSV_EXPRESSION = (
    "to_tsvector('english', title || ' ' || heading || ' ' || text) || "
    "to_tsvector('german', title || ' ' || heading || ' ' || text)"
)


def upgrade() -> None:
    op.create_table(
        "rulebook_chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        # The file in docs/rulebook and the heading's anchor in it.
        sa.Column("source", sa.String(length=100), nullable=False),
        sa.Column("anchor", sa.String(length=200), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(length=64), nullable=False),
        # SHA-256 of the whole file: which version of the rulebook the chunk comes from.
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        # The vector and its model; null until embedded (no key: full-text search only).
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("vector", Vector(768), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(TSV_EXPRESSION, persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rulebook_chunks")),
        sa.UniqueConstraint("source", "anchor", name=op.f("uq_rulebook_chunks_source_anchor")),
    )
    op.create_index("ix_rulebook_chunks_tsv", "rulebook_chunks", ["tsv"], postgresql_using="gin")
    op.execute(
        """
        CREATE VIEW history_lines WITH (security_barrier) AS
        SELECT b.invoice_id, b.source, b.supplier_vat_id, b.supplier_name, b.invoice_number,
               b.issue_date, b.line_no, b.text, b.text_sha256, b.account
        FROM bookings b
        LEFT JOIN invoices i ON i.id = b.invoice_id
        WHERE b.searchable
          AND (b.invoice_id IS NULL OR i.status = 'approved')
          AND NOT EXISTS (
              SELECT 1 FROM checks c
              WHERE c.invoice_id = b.invoice_id
                AND c.type = 'prompt_injection' AND c.status = 'failed'
          )
        """
    )
    op.execute(
        """
        CREATE VIEW history_invoices WITH (security_barrier) AS
        SELECT f.invoice_id,
               max(f.value) FILTER (WHERE f.code = 'BT-5') AS currency,
               max(f.value) FILTER (WHERE f.code = 'BT-109') AS net_total,
               max(f.value) FILTER (WHERE f.code = 'BT-112') AS gross_total,
               max(f.value) FILTER (WHERE f.code = 'BT-84') AS payee_iban
        FROM invoice_fields f
        WHERE f.line_no IS NULL
          AND f.invoice_id IN (SELECT invoice_id FROM history_lines WHERE invoice_id IS NOT NULL)
        GROUP BY f.invoice_id
        """
    )
    op.execute(
        """
        CREATE VIEW invoice_item_names WITH (security_barrier) AS
        SELECT invoice_id, line_no, value AS item_name
        FROM invoice_fields
        WHERE code = 'BT-153' AND line_no IS NOT NULL
        """
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{HISTORY_ROLE}') THEN
                CREATE ROLE {HISTORY_ROLE} NOLOGIN;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {HISTORY_ROLE}")
    op.execute(f"GRANT SELECT ON {', '.join(VIEWS)}, rulebook_chunks TO {HISTORY_ROLE}")
    op.execute(f"GRANT SELECT ({', '.join(EMBEDDING_COLUMNS)}) ON embeddings TO {HISTORY_ROLE}")


def downgrade() -> None:
    # The role stays: roles belong to the server (see migration 0010).
    op.execute(f"REVOKE ALL ON embeddings FROM {HISTORY_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {HISTORY_ROLE}")
    for view in reversed(VIEWS):
        op.execute(f"DROP VIEW {view}")
    op.drop_index("ix_rulebook_chunks_tsv", table_name="rulebook_chunks")
    op.drop_table("rulebook_chunks")
