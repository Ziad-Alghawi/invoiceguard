"""Counts the rows the api commits to its tables of record (R4-5, ADR-025): audit events (processed
invoices and decisions), check results, security events and model calls.

A listener on the app's session factory remembers the rows each flush inserts and counts them once
the transaction commits; a rollback forgets them. So a metric never counts a write that did not
happen, and the writers (processing, review, auth, agent, embeddings) need no metrics code.
"""

from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session, UOWTransaction, sessionmaker

from invoiceguard_api import metrics
from invoiceguard_api.models import AuditEvent, Check, ModelCall, SecurityEvent
from invoiceguard_api.processing import AUDIT_ACTION

# The statuses processing ends in; `processing` itself is a step, not an outcome.
PROCESSED_OUTCOMES = frozenset({"ready", "blocked", "failed", "awaiting_extraction"})
STATUS_CHANGED = "invoice.status_changed"
DECISION_BY_AUDIT_ACTION = {audit: action for action, audit in AUDIT_ACTION.items()}
_PENDING = "invoiceguard_metrics_rows"


def observe(row: object) -> None:
    if isinstance(row, AuditEvent):
        if row.action == STATUS_CHANGED and row.status_after in PROCESSED_OUTCOMES:
            metrics.INVOICES_PROCESSED.labels(row.status_after).inc()
        elif (action := DECISION_BY_AUDIT_ACTION.get(row.action)) is not None:
            metrics.DECISIONS.labels(action).inc()
    elif isinstance(row, Check):
        metrics.CHECK_RESULTS.labels(row.type, row.status.value).inc()
    elif isinstance(row, SecurityEvent):
        metrics.SECURITY_EVENTS.labels(row.type).inc()
    elif isinstance(row, ModelCall):
        metrics.LLM_CALLS.labels(row.purpose, row.model, row.status.value).inc()
        metrics.LLM_LATENCY.labels(row.purpose, row.model).observe(row.latency_ms / 1000)
        if row.cost_usd is not None:
            metrics.LLM_COST.labels(row.purpose, row.model).inc(float(row.cost_usd))
        for direction, tokens in (("input", row.input_tokens), ("output", row.output_tokens)):
            if tokens:
                metrics.LLM_TOKENS.labels(row.purpose, row.model, direction).inc(tokens)


def _remember_new_rows(session: Session, _: UOWTransaction) -> None:
    # During after_flush, session.new still lists the rows this flush inserted.
    session.info.setdefault(_PENDING, []).extend(session.new)


def _count_committed_rows(session: Session) -> None:
    for row in session.info.pop(_PENDING, []):
        observe(row)


def _forget_rows(session: Session, *_: Any) -> None:
    session.info.pop(_PENDING, None)


def count_committed_rows(session_factory: sessionmaker[Session]) -> None:
    """Count the rows each session of this factory commits."""
    event.listen(session_factory, "after_flush", _remember_new_rows)
    event.listen(session_factory, "after_commit", _count_committed_rows)
    event.listen(session_factory, "after_rollback", _forget_rows)
