"""Running the exception agent for an invoice and saving what it did (ADR-018).

The agent investigates blocked invoices only, and never one whose text looks like a prompt
injection (R2-4): that invoice is not sent to a model at all. A run writes only its own rows
(`agent_runs`, `agent_steps`) and its model calls (`model_calls`, purpose `agent`); it never
touches the invoice, its status, its audit log or its graph thread, and it takes no invoice lock,
so a reviewer can decide while it runs.

Without a model key (the public demo), `load_recorded` stores the result of a real earlier run
for the same case, clearly marked as recorded.
"""

import json
import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from importlib.resources import files
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from invoiceguard_api.agent.loop import ExceptionAgent, Outcome, StepRecord
from invoiceguard_api.checks.injection import CHECK_TYPE as INJECTION_CHECK
from invoiceguard_api.checks.supplier import normalise_vat_id
from invoiceguard_api.models import (
    AgentRun,
    AgentRunSource,
    AgentRunStatus,
    AgentStep,
    AgentStepKind,
    Check,
    CheckStatus,
    Invoice,
    InvoiceField,
    InvoiceStatus,
    ModelCall,
    ModelCallStatus,
    Supplier,
)
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS, LINE_TERMS
from invoiceguard_api.processing import spent_today_usd

logger = logging.getLogger(__name__)

AGENT_PURPOSE = "agent"
# Blocked, and still blocked while an approver looks at an override request.
INVESTIGABLE = frozenset({InvoiceStatus.BLOCKED, InvoiceStatus.OVERRIDE_REQUESTED})
NOT_BLOCKED = "Only blocked invoices are investigated."
INJECTION_SUSPECTED = (
    "Not investigated: the invoice text looks like a prompt injection, so it is not sent to a "
    "model. Check it by hand."
)
DAILY_BUDGET = "The daily LLM budget (INVOICEGUARD_LLM_DAILY_BUDGET_USD) is used up."
INTERRUPTED = "The run was interrupted by an API restart."
INTERNAL_ERROR = "The run failed with an internal error; see the API logs."
SELLER_VAT_ID = DOCUMENT_TERMS["seller_vat_id"]
RECORDED = files("invoiceguard_api") / "agent" / "recorded"
# Per check in the case file (see _check_entry).
MAX_MESSAGE_CHARS = 400
MAX_EVIDENCE_CHARS = 1500
_TERM_NAMES = {code: name for name, code in (DOCUMENT_TERMS | LINE_TERMS).items()}


class AlreadyRunning(Exception):
    """An investigation of this invoice is running already."""


def refusal(session: Session, invoice: Invoice) -> str | None:
    """Why the invoice may not be investigated, or None if it may."""
    if invoice.status not in INVESTIGABLE:
        return NOT_BLOCKED
    injected = session.scalar(
        select(func.count(Check.id)).where(
            Check.invoice_id == invoice.id,
            Check.type == INJECTION_CHECK,
            Check.status == CheckStatus.FAILED,
        )
    )
    return INJECTION_SUSPECTED if injected else None


def _seller_vat_id(session: Session, invoice_id: uuid.UUID) -> str | None:
    return session.scalar(
        select(InvoiceField.value).where(
            InvoiceField.invoice_id == invoice_id,
            InvoiceField.code == SELLER_VAT_ID,
            InvoiceField.line_no.is_(None),
        )
    )


def _failed_checks(session: Session, invoice_id: uuid.UUID) -> list[str]:
    return sorted(
        session.scalars(
            select(Check.type).where(
                Check.invoice_id == invoice_id, Check.status == CheckStatus.FAILED
            )
        )
    )


def case_file(session: Session, invoice_id: uuid.UUID) -> dict[str, Any]:
    """What the agent is told: the invoice's fields and the checks that did not pass. Values
    only, never the raw document; all of it is untrusted."""
    fields = session.scalars(
        select(InvoiceField)
        .where(InvoiceField.invoice_id == invoice_id)
        .order_by(InvoiceField.line_no.asc().nulls_first(), InvoiceField.code)
    ).all()
    document: dict[str, str] = {}
    lines: dict[int, dict[str, Any]] = {}
    for field in fields:
        name = _TERM_NAMES.get(field.code, field.code)
        if field.line_no is None:
            document[name] = field.value
        else:
            lines.setdefault(field.line_no, {"line_no": field.line_no})[name] = field.value
    checks = session.scalars(
        select(Check)
        .where(Check.invoice_id == invoice_id, Check.status != CheckStatus.PASSED)
        .order_by(Check.status, Check.type)
    ).all()
    return {
        "invoice": document,
        "lines": list(lines.values()),
        "checks": [_check_entry(check) for check in checks],
    }


def _check_entry(check: Check) -> dict[str, Any]:
    """A check for the case file, bounded in size: evidence can grow with the data (a duplicate
    warning lists every similar invoice), and every step sends the case again."""
    entry: dict[str, Any] = {
        "type": check.type,
        "status": check.status.value,
        "message": check.message[:MAX_MESSAGE_CHARS],
    }
    if check.status is CheckStatus.FAILED:
        evidence = json.dumps(check.evidence, ensure_ascii=False, default=str)
        entry["evidence"] = (
            check.evidence if len(evidence) <= MAX_EVIDENCE_CHARS else "omitted: too long"
        )
    return entry


def contact_email(session: Session, invoice_id: uuid.UUID) -> str | None:
    """The supplier's address from the master data, by the invoice's seller VAT ID. Never an
    address from the invoice or from the model (ADR-018)."""
    vat_id = _seller_vat_id(session, invoice_id)
    if vat_id is None:
        return None
    return session.scalar(
        select(Supplier.contact_email).where(Supplier.vat_id == normalise_vat_id(vat_id))
    )


def agent_spent_usd(session: Session, invoice_id: uuid.UUID) -> Decimal:
    """What every agent run for this invoice has cost so far: the base of the cost cap."""
    spent: Decimal = session.scalar(
        select(func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(
            ModelCall.invoice_id == invoice_id, ModelCall.purpose == AGENT_PURPOSE
        )
    )
    return spent


def start_run(
    session: Session,
    invoice_id: uuid.UUID,
    model: str,
    user_id: uuid.UUID | None,
    source: AgentRunSource = AgentRunSource.LIVE,
) -> AgentRun:
    """Add a run in status `running` and commit; raises AlreadyRunning if one is running."""
    run = AgentRun(
        invoice_id=invoice_id,
        status=AgentRunStatus.RUNNING,
        source=source,
        user_id=user_id,
        model=model,
    )
    session.add(run)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise AlreadyRunning from None
    return run


def _call_status(record: StepRecord) -> ModelCallStatus:
    if record.input_tokens is None:
        return ModelCallStatus.ERROR
    if record.cost_usd is None:
        return ModelCallStatus.PRICE_UNKNOWN
    if record.error is not None:
        return ModelCallStatus.INVALID_OUTPUT
    return ModelCallStatus.OK


def _save_step(
    session_factory: sessionmaker[Session], run_id: uuid.UUID, invoice_id: uuid.UUID, model: str
) -> Callable[[StepRecord], None]:
    def save(record: StepRecord) -> None:
        with session_factory() as session:
            session.add(
                AgentStep(
                    run_id=run_id,
                    step_no=record.step_no,
                    kind=record.kind,
                    tool=record.tool,
                    argument=record.argument,
                    result=record.result,
                    input_tokens=record.input_tokens,
                    output_tokens=record.output_tokens,
                    cost_usd=record.cost_usd,
                    latency_ms=record.latency_ms,
                    error=record.error,
                    at=record.at,
                )
            )
            if record.kind is AgentStepKind.MODEL:
                session.add(
                    ModelCall(
                        invoice_id=invoice_id,
                        purpose=AGENT_PURPOSE,
                        model=model,
                        status=_call_status(record),
                        input_tokens=record.input_tokens,
                        output_tokens=record.output_tokens,
                        cost_usd=record.cost_usd,
                        latency_ms=record.latency_ms,
                        error=record.error,
                        at=record.at,
                    )
                )
                session.execute(
                    update(AgentRun)
                    .where(AgentRun.id == run_id)
                    .values(
                        input_tokens=AgentRun.input_tokens + (record.input_tokens or 0),
                        output_tokens=AgentRun.output_tokens + (record.output_tokens or 0),
                        cost_usd=AgentRun.cost_usd + (record.cost_usd or 0),
                    )
                )
            session.commit()

    return save


def _finish(
    session_factory: sessionmaker[Session], run_id: uuid.UUID, outcome: Outcome, duration_ms: int
) -> None:
    with session_factory() as session:
        run = session.get_one(AgentRun, run_id)
        run.status = outcome.status
        run.stop_reason = outcome.stop_reason
        run.error = outcome.error
        run.finding = outcome.finding
        run.email_subject = outcome.email_subject
        run.email_body = outcome.email_body
        if outcome.status is AgentRunStatus.COMPLETED:
            run.email_to = contact_email(session, run.invoice_id)
        run.finished_at = datetime.now(UTC)
        run.duration_ms = duration_ms
        session.commit()


def run_investigation(
    session_factory: sessionmaker[Session], agent: ExceptionAgent, run_id: uuid.UUID
) -> None:
    """Run the agent for a started run and save the outcome; any error ends the run `failed`."""
    started = time.perf_counter()
    with session_factory() as session:
        run = session.get_one(AgentRun, run_id)
        invoice_id = run.invoice_id
        case = case_file(session, invoice_id)
        spent = agent_spent_usd(session, invoice_id)
        budget = agent.daily_budget_usd
        over_budget = budget is not None and spent_today_usd(session) >= budget
    try:
        if over_budget:
            outcome = Outcome(AgentRunStatus.STOPPED, "daily_budget", DAILY_BUDGET)
        else:
            outcome = agent.investigate(
                case, spent, _save_step(session_factory, run_id, invoice_id, agent.model)
            )
    except Exception:
        logger.exception("Agent run %s for invoice %s failed", run_id, invoice_id)
        outcome = Outcome(AgentRunStatus.FAILED, "internal_error", INTERNAL_ERROR)
    _finish(session_factory, run_id, outcome, round((time.perf_counter() - started) * 1000))
    logger.info(
        "Agent run %s for invoice %s: %s %s",
        run_id,
        invoice_id,
        outcome.status.value,
        outcome.stop_reason or "",
    )


def investigate_if_blocked(
    session_factory: sessionmaker[Session], agent: ExceptionAgent | None, invoice_id: uuid.UUID
) -> None:
    """After processing: investigate the invoice if it ended blocked and may be investigated."""
    if agent is None:
        return
    with session_factory() as session:
        invoice = session.get(Invoice, invoice_id)
        if invoice is None or invoice.status is not InvoiceStatus.BLOCKED:
            return
        if (reason := refusal(session, invoice)) is not None:
            logger.info("Invoice %s not investigated: %s", invoice_id, reason)
            return
        try:
            run = start_run(session, invoice_id, agent.model, None)
        except AlreadyRunning:
            return
    run_investigation(session_factory, agent, run.id)


def fail_interrupted(session_factory: sessionmaker[Session]) -> int:
    """On startup: runs a restart left `running` can never finish; mark them failed."""
    with session_factory() as session:
        result = session.execute(
            update(AgentRun)
            .where(AgentRun.status == AgentRunStatus.RUNNING)
            .values(
                status=AgentRunStatus.FAILED,
                stop_reason="interrupted",
                error=INTERRUPTED,
                finished_at=datetime.now(UTC),
            )
            .returning(AgentRun.id)
        )
        count = len(result.all())
        session.commit()
    return count


def _recordings() -> list[dict[str, Any]]:
    return [
        json.loads(entry.read_text("utf-8"))
        for entry in RECORDED.iterdir()
        if entry.name.endswith(".json")
    ]


def case_key(session: Session, invoice_id: uuid.UUID) -> dict[str, Any]:
    """What makes two invoices the same case for a recording: the seller's VAT ID and the
    failed checks, so a copy of a sample with another invoice number matches too."""
    vat_id = _seller_vat_id(session, invoice_id)
    return {
        "seller_vat_id": None if vat_id is None else normalise_vat_id(vat_id),
        "failed_checks": _failed_checks(session, invoice_id),
    }


def recording_for(session: Session, invoice_id: uuid.UUID) -> dict[str, Any] | None:
    """The recorded run for the same case (`case_key`), if one is packaged."""
    key = case_key(session, invoice_id)
    return next((r for r in _recordings() if r["scenario"] == key), None)


def load_recorded(
    session: Session, invoice_id: uuid.UUID, recording: dict[str, Any], user_id: uuid.UUID
) -> AgentRun:
    """Store a recorded run for the invoice, marked as recorded, with its original numbers."""
    now = datetime.now(UTC)
    run = AgentRun(
        invoice_id=invoice_id,
        status=AgentRunStatus.COMPLETED,
        source=AgentRunSource.RECORDED,
        user_id=user_id,
        model=recording["model"],
        finding=recording["finding"],
        email_to=contact_email(session, invoice_id),
        email_subject=recording["email_subject"],
        email_body=recording["email_body"],
        input_tokens=recording["input_tokens"],
        output_tokens=recording["output_tokens"],
        cost_usd=Decimal(recording["cost_usd"]),
        started_at=now,
        finished_at=now,
        duration_ms=recording["duration_ms"],
        recorded_at=datetime.fromisoformat(recording["recorded_at"]),
        steps=[
            AgentStep(
                **{
                    **step,
                    "kind": AgentStepKind(step["kind"]),
                    "cost_usd": None if step["cost_usd"] is None else Decimal(step["cost_usd"]),
                }
            )
            for step in recording["steps"]
        ],
    )
    session.add(run)
    session.commit()
    return run


def latest_run(session: Session, invoice_id: uuid.UUID) -> AgentRun | None:
    return session.scalars(
        select(AgentRun)
        .where(AgentRun.invoice_id == invoice_id)
        .order_by(AgentRun.started_at.desc(), AgentRun.id)
        .limit(1)
    ).first()
