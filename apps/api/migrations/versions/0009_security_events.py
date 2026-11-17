"""Security events (R2-4): an append-only log of failed logins, lockouts, refused role checks,
self-approval attempts and prompt injections found in invoices.

Like audit_events, a trigger rejects UPDATE and DELETE. invoice_id has no foreign key: the demo
reset deletes invoices, and their security events stay.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-17 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "security_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "low",
                "medium",
                "high",
                name="security_severity",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("invoice_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_security_events_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_events")),
    )
    op.create_index("ix_security_events_at", "security_events", ["at"], unique=False)
    op.create_index("ix_security_events_type", "security_events", ["type"], unique=False)
    op.create_index(
        "ix_security_events_invoice_id", "security_events", ["invoice_id"], unique=False
    )
    # TRUNCATE stays possible for the table owner (test database resets), as for audit_events.
    op.execute(
        """
        CREATE FUNCTION security_events_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'security_events is append-only: % is not allowed', TG_OP;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER security_events_append_only
        BEFORE UPDATE OR DELETE ON security_events
        FOR EACH ROW EXECUTE FUNCTION security_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER security_events_append_only ON security_events")
    op.execute("DROP FUNCTION security_events_append_only()")
    op.drop_index("ix_security_events_invoice_id", table_name="security_events")
    op.drop_index("ix_security_events_type", table_name="security_events")
    op.drop_index("ix_security_events_at", table_name="security_events")
    op.drop_table("security_events")
