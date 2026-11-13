"""Review and login (ADR-011, ADR-012): users, sessions, review statuses, audit columns.

audit_events gets the reviewer, the status before and after, and the reason as columns, and a
trigger that rejects UPDATE and DELETE, so the log is append-only. Existing status-change events
move their from/to/reason out of `details` into the new columns.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_STATUSES = ("received", "processing", "ready", "blocked", "failed", "awaiting_extraction")
NEW_STATUSES = (*OLD_STATUSES, "approved", "rejected")


def _status_check(statuses: tuple[str, ...]) -> None:
    op.drop_constraint(op.f("ck_invoices_invoice_status"), "invoices", type_="check")
    values = ", ".join(f"'{status}'" for status in statuses)
    op.create_check_constraint(
        op.f("ck_invoices_invoice_status"), "invoices", sa.text(f"status IN ({values})")
    )


def upgrade() -> None:
    _status_check(NEW_STATUSES)
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("failed_logins", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_sessions")),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)

    op.add_column("audit_events", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.add_column("audit_events", sa.Column("status_before", sa.String(length=20), nullable=True))
    op.add_column("audit_events", sa.Column("status_after", sa.String(length=20), nullable=True))
    op.add_column("audit_events", sa.Column("reason", sa.Text(), nullable=True))
    # No ON DELETE action: a user with audit history cannot be deleted (SET NULL would be an
    # UPDATE, which the trigger below rejects anyway).
    op.create_foreign_key(
        op.f("fk_audit_events_user_id_users"), "audit_events", "users", ["user_id"], ["id"]
    )
    op.execute(
        """
        UPDATE audit_events
        SET status_before = details->>'from',
            status_after = details->>'to',
            reason = details->>'reason',
            details = details - 'from' - 'to' - 'reason'
        WHERE action = 'invoice.status_changed'
        """
    )
    # TRUNCATE stays possible for the table owner (test database resets); the application only
    # ever inserts.
    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: % is not allowed', TG_OP;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION audit_events_append_only()")
    # The old schema has no review outcome: back to the status before the decision, which the
    # audit log keeps (the decision itself stays in the log).
    op.execute(
        """
        UPDATE invoices SET status = (
            SELECT status_before FROM audit_events
            WHERE entity_type = 'invoice' AND entity_id = invoices.id::text
            AND action IN ('invoice.approved', 'invoice.rejected')
            ORDER BY id DESC LIMIT 1
        )
        WHERE status IN ('approved', 'rejected')
        """
    )
    op.execute(
        """
        UPDATE audit_events
        SET details = details || jsonb_build_object(
            'from', status_before, 'to', status_after, 'reason', reason
        )
        WHERE action = 'invoice.status_changed'
        """
    )
    op.drop_constraint(op.f("fk_audit_events_user_id_users"), "audit_events", type_="foreignkey")
    op.drop_column("audit_events", "reason")
    op.drop_column("audit_events", "status_after")
    op.drop_column("audit_events", "status_before")
    op.drop_column("audit_events", "user_id")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
    _status_check(OLD_STATUSES)
