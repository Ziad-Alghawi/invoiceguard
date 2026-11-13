"""ORM models for the R1 tables. The schema itself is owned by the Alembic migrations."""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Stable constraint names, so migrations can alter and drop them by name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class InvoiceStatus(enum.StrEnum):
    """Processing status (ADR-007) and, in R1, the review outcome (ADR-012)."""

    RECEIVED = "received"
    PROCESSING = "processing"
    # A PDF without embedded XML, waiting for LLM extraction (R1-5).
    AWAITING_EXTRACTION = "awaiting_extraction"
    READY = "ready"
    BLOCKED = "blocked"
    FAILED = "failed"
    # Set only by a logged-in reviewer (ADR-012); final.
    APPROVED = "approved"
    REJECTED = "rejected"


class SourceType(enum.StrEnum):
    XML = "xml"
    PDF = "pdf"


class FieldSource(enum.StrEnum):
    XML = "xml"
    LLM = "llm"


class ModelCallStatus(enum.StrEnum):
    OK = "ok"
    # The reply was not valid JSON or broke the schema.
    INVALID_OUTPUT = "invalid_output"
    # The price table has no price for the model: an error, never zero cost (ADR-004).
    PRICE_UNKNOWN = "price_unknown"
    # The call itself failed (quota, key, timeout, provider error).
    ERROR = "error"


class CheckStatus(enum.StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


def _str_enum(enum_class: type[enum.StrEnum], name: str) -> Enum:
    # VARCHAR + CHECK instead of a native PostgreSQL enum: adding a value is a plain migration.
    return Enum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [member.value for member in members],
    )


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = _uuid_pk()
    status: Mapped[InvoiceStatus] = mapped_column(
        _str_enum(InvoiceStatus, "invoice_status"), default=InvoiceStatus.RECEIVED
    )
    # Why the invoice is in its status, for example the parse error of a `failed` invoice.
    status_reason: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[SourceType] = mapped_column(_str_enum(SourceType, "source_type"))
    original_filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    # Relative to the storage root, so the volume can be mounted anywhere.
    storage_path: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    fields: Mapped[list["InvoiceField"]] = relationship(back_populates="invoice")
    checks: Mapped[list["Check"]] = relationship(back_populates="invoice")

    __table_args__ = (Index("ix_invoices_created_at", "created_at"),)


class InvoiceField(Base):
    """One EN 16931 business term (BT-1, BT-84, ...) read from an invoice."""

    __tablename__ = "invoice_fields"

    id: Mapped[uuid.UUID] = _uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(20))
    # Null for document-level terms; the 1-based line number for invoice-line terms.
    line_no: Mapped[int | None] = mapped_column(Integer)
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[FieldSource] = mapped_column(_str_enum(FieldSource, "field_source"))
    # Null for values read from XML; 0..1 for LLM extraction.
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    # LLM extraction only: where the value is printed, {"page": 1, "snippet": "..."}.
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()

    invoice: Mapped[Invoice] = relationship(back_populates="fields")

    __table_args__ = (
        UniqueConstraint("invoice_id", "code", "line_no", postgresql_nulls_not_distinct=True),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),
    )


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255))
    vat_id: Mapped[str] = mapped_column(String(20), unique=True)
    street: Mapped[str] = mapped_column(String(255))
    postal_code: Mapped[str] = mapped_column(String(20))
    city: Mapped[str] = mapped_column(String(100))
    country_code: Mapped[str] = mapped_column(String(2))
    created_at: Mapped[datetime] = _created_at()

    bank_accounts: Mapped[list["SupplierBankAccount"]] = relationship(back_populates="supplier")


class SupplierBankAccount(Base):
    """Bank account in the supplier registry; only verified accounts count as known."""

    __tablename__ = "supplier_bank_accounts"

    id: Mapped[uuid.UUID] = _uuid_pk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id", ondelete="CASCADE"))
    iban: Mapped[str] = mapped_column(String(34))
    verified: Mapped[bool] = mapped_column(default=False)
    since: Mapped[date] = mapped_column(Date)
    verified_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created_at()

    supplier: Mapped[Supplier] = relationship(back_populates="bank_accounts")

    __table_args__ = (UniqueConstraint("supplier_id", "iban"),)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = _uuid_pk()
    number: Mapped[str] = mapped_column(String(50), unique=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"))
    order_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = _created_at()

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", order_by="PurchaseOrderLine.line_no"
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[uuid.UUID] = _uuid_pk()
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE")
    )
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    # UN/ECE Recommendation 20 code, as on the invoice (C62 = piece, HUR = hour).
    unit_code: Mapped[str] = mapped_column(String(3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")

    __table_args__ = (UniqueConstraint("purchase_order_id", "line_no"),)


class Check(Base):
    """Result of one deterministic check on an invoice, with the evidence it used."""

    __tablename__ = "checks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    invoice_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(50))
    status: Mapped[CheckStatus] = mapped_column(_str_enum(CheckStatus, "check_status"))
    # One sentence for the reviewer, for example why the IBAN check failed.
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = _created_at()

    invoice: Mapped[Invoice] = relationship(back_populates="checks")

    __table_args__ = (Index("ix_checks_invoice_id", "invoice_id"),)


class User(Base):
    """A seeded reviewer (ADR-006); there is no sign-up."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    # Stored lower-case; login compares lower-case.
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(255))
    # Argon2id hash in PHC string format, never the password.
    password_hash: Mapped[str] = mapped_column(String(255))
    # Failed logins in a row; reset by a successful login or when a lockout starts (ADR-011).
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class UserSession(Base):
    """A login session (ADR-011). Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()

    __table_args__ = (Index("ix_sessions_user_id", "user_id"),)


class AuditEvent(Base):
    """Append-only log of who did what to which entity.

    A database trigger rejects UPDATE and DELETE (migration 0005). Rows are ordered by `id`, not
    by `at` (see docs/status.md, lessons learned).
    """

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # The user's email, or "system" / "anonymous" / "seed" for actions without a logged-in user.
    actor: Mapped[str] = mapped_column(String(255))
    # The logged-in user who acted; null for system actions and failed logins.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(64))
    # Invoice status before and after the action, for actions that change it.
    status_before: Mapped[str | None] = mapped_column(String(20))
    status_after: Mapped[str | None] = mapped_column(String(20))
    # Why: a reviewer's reject or override reason, or the reason for a processing status.
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    __table_args__ = (Index("ix_audit_events_entity", "entity_type", "entity_id"),)


class ModelCall(Base):
    """One LLM call with its tokens, cost and latency (ADR-004), also when it failed.

    Append-only like `audit_events`: the identity id gives the order of calls.
    """

    __tablename__ = "model_calls"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Null for calls not made for one invoice; kept when an invoice is deleted, for cost totals.
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="SET NULL")
    )
    # Which LLM step made the call (ADR-002), for example "extraction".
    purpose: Mapped[str] = mapped_column(String(50))
    # The LiteLLM model string, for example gemini/gemini-3.8-flash.
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[ModelCallStatus] = mapped_column(_str_enum(ModelCallStatus, "model_call_status"))
    # Null when the call failed before the provider reported usage.
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    # US dollars, as LiteLLM's price table; null when no price is known or the call failed.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int] = mapped_column(Integer)
    # Why the call did not succeed; never the document text.
    error: Mapped[str | None] = mapped_column(Text)
    # When the call started.
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_model_calls_invoice_id", "invoice_id"),
        # For the per-day cost total and cap.
        Index("ix_model_calls_at", "at"),
    )
