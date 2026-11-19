"""Invoice processing as a LangGraph graph (ADR-007, ADR-015): one thread per invoice, the
thread ID is the invoice ID, and the state is checkpointed in PostgreSQL (checkpoints.py).

    START ─┬─ read ────┬─ checks ─┬─ review ─ decide ─ END
           ├─ extract ─┴──────────┤     ▲          │
           └──────────────────────┘     └──────────┘ while the invoice stays in review

    and decide ─ read when a rejected invoice is reopened.

- read: reads the XML and validates it with KoSIT (ADR-009). A PDF without XML ends in
  `awaiting_extraction`, a file that cannot be read in `failed`; both go straight to review.
- extract: the LLM extraction of a plain PDF (ADR-010), awaiting_extraction → processing.
- checks: stores the fields and runs the checks; any failed check ends in `blocked`, else `ready`.
- review: pauses with `interrupt()`. Only a reviewer's decision resumes it (review.py).
- decide: writes the decision's status and its audit row in one transaction: `approved`,
  `rejected`, or for the four-eyes override (ADR-016) `override_requested` (then the thread
  pauses at review again for an approver) and back to `blocked` when the approver declines.
  Reopening a rejected invoice (ADR-016) writes `processing`, clears the old fields and check
  results and goes on to read, so the checks run again on today's master data.

Every run ends paused at review, whatever its outcome, because a reviewer can reject failed and
waiting invoices too. A new run on a thread (extraction after waiting, a re-run after a restart)
starts again from START; a run that starts at review only pauses an invoice for its decision.

A run starts after a claim, a conditional update to `processing`, and holds the invoice's
advisory lock, as every decision does, so work on one thread happens one at a time. Status
changes write audit events. Plain sync functions: FastAPI runs them in its thread pool (ADR-008).
"""

import logging
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal, NotRequired, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from pydantic import TypeAdapter
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from invoiceguard_api.booking.record import BookingChoice, record_bookings
from invoiceguard_api.checkpoints import (
    engine_of,
    invoice_lock,
    open_checkpointer,
    try_lock_invoice,
)
from invoiceguard_api.checks import (
    KositValidator,
    final_status,
    load_context,
    replace_results,
    run_checks,
    summarise,
)
from invoiceguard_api.checks.model import Validation
from invoiceguard_api.extraction import Extraction, PdfExtractor
from invoiceguard_api.extraction.model import FieldConfidence
from invoiceguard_api.injection import InjectionScan
from invoiceguard_api.injection import scan as scan_injection
from invoiceguard_api.models import (
    AuditEvent,
    Check,
    CheckStatus,
    FieldSource,
    Invoice,
    InvoiceField,
    InvoiceStatus,
    ModelCall,
    SecuritySeverity,
    SourceType,
    User,
    UserRole,
)
from invoiceguard_api.parsing import (
    NoEmbeddedXml,
    ParsedInvoice,
    ParseError,
    invoice_xml,
    read_invoice_xml,
)
from invoiceguard_api.parsing.fields import to_field_rows
from invoiceguard_api.security import INJECTION, security_event
from invoiceguard_api.storage import FileStorage

logger = logging.getLogger(__name__)

SYSTEM_ACTOR = "system"
AWAITING_EXTRACTION_REASON = "The PDF has no embedded e-invoice XML; it needs LLM extraction."
EXTRACTION_OFF_REASON = (
    "The PDF has no embedded e-invoice XML, and LLM extraction is skipped: no API key is "
    "configured (INVOICEGUARD_LLM_API_KEY)."
)
BUDGET_REASON = (
    "The daily LLM budget (INVOICEGUARD_LLM_DAILY_BUDGET_USD) is used up; the PDF is extracted "
    "after the next API restart on a later day."
)
INTERNAL_ERROR_REASON = "Processing failed with an internal error; see the API logs."
RESTART_REASON = "Reset after an API restart interrupted processing."
EXTRACTION_PURPOSE = "extraction"
NO_XML = Validation(
    outcome="not_applicable",
    reason="No e-invoice XML to validate: the fields were extracted from the PDF by an LLM.",
)
# The statuses a thread is paused at review in: a reviewer can decide on these.
IN_REVIEW = frozenset(
    {
        InvoiceStatus.READY,
        InvoiceStatus.BLOCKED,
        InvoiceStatus.FAILED,
        InvoiceStatus.AWAITING_EXTRACTION,
        InvoiceStatus.OVERRIDE_REQUESTED,
    }
)

Start = Literal["read", "extract", "review"]
Action = Literal[
    "approve", "reject", "request_override", "confirm_override", "decline_override", "reopen"
]
# The status each decision writes; reject is allowed in every review status.
NEW_STATUS: dict[Action, InvoiceStatus] = {
    "approve": InvoiceStatus.APPROVED,
    "reject": InvoiceStatus.REJECTED,
    "request_override": InvoiceStatus.OVERRIDE_REQUESTED,
    "confirm_override": InvoiceStatus.APPROVED,
    "decline_override": InvoiceStatus.BLOCKED,
    "reopen": InvoiceStatus.PROCESSING,
}
AUDIT_ACTION: dict[Action, str] = {
    "approve": "invoice.approved",
    "reject": "invoice.rejected",
    "request_override": "invoice.override_requested",
    "confirm_override": "invoice.override_confirmed",
    "decline_override": "invoice.override_declined",
    "reopen": "invoice.reopened",
}


class Decision(TypedDict):
    """A reviewer's decision, the value that resumes a thread paused at review."""

    action: Action
    user_id: str
    actor: str
    # The status the reviewer decided on; decide refuses to write if it has changed since.
    status_before: str
    reason: str | None
    # Approve and confirm_override: the account the user chose per line (ADR-020); written
    # with the decision. Not set by older clients and other decisions.
    bookings: NotRequired[list[BookingChoice]]


# The decisions that approve an invoice, and with it the accounts chosen for its lines.
APPROVING: frozenset[Action] = frozenset({"approve", "confirm_override"})


class RunState(TypedDict, total=False):
    """The checkpointed state: plain JSON values only (see checkpoints.py)."""

    invoice_id: str
    start: Start
    # What read or extract hands to checks (a `Reading` as JSON); None when there is nothing.
    reading: dict[str, Any] | None
    decision: Decision


@dataclass(frozen=True)
class Reading:
    """The invoice as read from XML or extracted by an LLM, before the checks."""

    invoice: ParsedInvoice
    validation: Validation
    # Set for LLM extraction only: a confidence per field (ADR-010).
    confidences: tuple[FieldConfidence, ...] | None = None
    confidence_threshold: Decimal = Decimal(1)
    # Added to the audit event of the final status (the extraction's model and cost).
    details: dict[str, Any] | None = None
    # The prompt-injection scan of the document text (R2-4); None for a reading from a
    # checkpoint written before the scan existed.
    injection: InjectionScan | None = None


READING = TypeAdapter(Reading)


@dataclass(frozen=True)
class Services:
    """What the nodes work with; passed to each run as its context, never checkpointed."""

    session_factory: sessionmaker[Session]
    storage: FileStorage
    # Only a run that reads XML needs the validator, only extraction the extractor.
    validator: KositValidator | None
    extractor: PdfExtractor | None


class StaleDecision(Exception):
    """The invoice is no longer in the status the reviewer decided on; nothing was written."""


class ReopenRefused(Exception):
    """Only a rejected invoice is reopened (never an approved one, ADR-016); nothing was
    written. The endpoint checks this first; decide checks it again."""


class ForbiddenDecision(Exception):
    """The user may not make this decision (not an approver, or their own override request);
    nothing was written. The endpoints check this first; decide checks it again."""


# --- Status and audit writes -------------------------------------------------------------------


def _status_event(
    invoice_id: uuid.UUID,
    old: InvoiceStatus,
    new: InvoiceStatus,
    reason: str | None,
    **extra: Any,
) -> AuditEvent:
    return AuditEvent(
        actor=SYSTEM_ACTOR,
        action="invoice.status_changed",
        entity_type="invoice",
        entity_id=str(invoice_id),
        status_before=old.value,
        status_after=new.value,
        reason=reason,
        details=extra,
    )


def _claim(session: Session, invoice_id: uuid.UUID, waiting: InvoiceStatus) -> bool:
    """Move an invoice from `waiting` to `processing`; False if another run has it or it is done."""
    claimed = session.execute(
        update(Invoice)
        .where(Invoice.id == invoice_id, Invoice.status == waiting)
        .values(status=InvoiceStatus.PROCESSING, status_reason=None)
        .returning(Invoice.id)
    ).scalar_one_or_none()
    if claimed is None:
        session.rollback()
        return False
    session.add(_status_event(invoice_id, waiting, InvoiceStatus.PROCESSING, None))
    session.commit()
    return True


def _finish(
    session: Session,
    invoice: Invoice,
    status: InvoiceStatus,
    reason: str | None,
    **extra: Any,
) -> None:
    session.add(_status_event(invoice.id, invoice.status, status, reason, **extra))
    invoice.status = status
    invoice.status_reason = reason
    session.commit()
    logger.info("Invoice %s is %s", invoice.id, status.value)


def _fail_internal(session: Session, invoice: Invoice, step: str) -> None:
    """After an unexpected error: log it, drop the step's writes and end in `failed`."""
    logger.exception("%s invoice %s failed", step, invoice.id)
    session.rollback()
    _finish(session, invoice, InvoiceStatus.FAILED, INTERNAL_ERROR_REASON)


def _status(session_factory: sessionmaker[Session], invoice_id: uuid.UUID) -> InvoiceStatus | None:
    with session_factory() as session:
        return session.scalar(select(Invoice.status).where(Invoice.id == invoice_id))


def override_requester(session: Session, invoice_id: uuid.UUID) -> uuid.UUID | None:
    """The user who made the invoice's latest override request, from the audit log."""
    return session.scalar(
        select(AuditEvent.user_id)
        .where(
            AuditEvent.entity_type == "invoice",
            AuditEvent.entity_id == str(invoice_id),
            AuditEvent.action == AUDIT_ACTION["request_override"],
        )
        .order_by(AuditEvent.id.desc())
        .limit(1)
    )


def failed_checks(session: Session, invoice_id: uuid.UUID) -> list[str]:
    """The types of the invoice's failed checks, sorted."""
    return list(
        session.scalars(
            select(Check.type)
            .where(Check.invoice_id == invoice_id, Check.status == CheckStatus.FAILED)
            .order_by(Check.type)
        )
    )


# --- Reading and checks -------------------------------------------------------------------------


def _xml_fields(invoice_id: uuid.UUID, parsed: ParsedInvoice) -> list[InvoiceField]:
    return [
        InvoiceField(
            invoice_id=invoice_id,
            code=row.code,
            line_no=row.line_no,
            value=row.value,
            source=FieldSource.XML,
        )
        for row in to_field_rows(parsed)
    ]


def _llm_fields(invoice_id: uuid.UUID, extraction: Extraction) -> list[InvoiceField]:
    """Each row with its confidence and evidence; line terms share their line's (ADR-010)."""
    terms = {field.code: field for field in extraction.confidences if field.code is not None}
    lines = {field.line_no: field for field in extraction.confidences if field.line_no is not None}
    rows = []
    for row in to_field_rows(extraction.invoice):
        field = terms[row.code] if row.line_no is None else lines[row.line_no]
        rows.append(
            InvoiceField(
                invoice_id=invoice_id,
                code=row.code,
                line_no=row.line_no,
                value=row.value,
                source=FieldSource.LLM,
                confidence=field.confidence,
                evidence=field.evidence,
            )
        )
    return rows


def _check_and_finish(session: Session, invoice: Invoice, reading: Reading) -> None:
    """Replace the fields and check results and set the final status, in one transaction."""
    parsed = reading.invoice
    extraction = None if reading.confidences is None else Extraction(parsed, reading.confidences)
    fields = (
        _xml_fields(invoice.id, parsed)
        if extraction is None
        else _llm_fields(invoice.id, extraction)
    )
    session.execute(delete(InvoiceField).where(InvoiceField.invoice_id == invoice.id))
    session.add_all(fields)
    context = load_context(
        session,
        invoice.id,
        parsed,
        reading.validation,
        extraction,
        reading.confidence_threshold,
        reading.injection,
    )
    results = run_checks(context)
    replace_results(session, invoice.id, results)
    if reading.injection is not None and reading.injection.findings:
        session.add(
            security_event(
                INJECTION,
                SecuritySeverity.HIGH,
                invoice_id=invoice.id,
                sources=list(reading.injection.sources),
                findings=[asdict(finding) for finding in reading.injection.findings],
            )
        )
    summary = summarise(results)
    status = final_status(results)
    reason = (
        None
        if status is InvoiceStatus.READY
        else "Failed checks: " + ", ".join(summary["failed_checks"]) + "."
    )
    _finish(
        session,
        invoice,
        status,
        reason,
        syntax=parsed.syntax,
        warnings=list(parsed.warnings),
        checks=summary,
        **(reading.details or {}),
    )


def _read_xml(
    session: Session,
    storage: FileStorage,
    validator: KositValidator,
    extraction_on: bool,
    invoice: Invoice,
) -> Reading | None:
    try:
        content = storage.read(invoice.storage_path)
        xml = invoice_xml(content, invoice.source_type)
        parsed = read_invoice_xml(xml)
    except NoEmbeddedXml:
        reason = AWAITING_EXTRACTION_REASON if extraction_on else EXTRACTION_OFF_REASON
        _finish(session, invoice, InvoiceStatus.AWAITING_EXTRACTION, reason)
        return None
    except ParseError as error:
        _finish(session, invoice, InvoiceStatus.FAILED, str(error))
        return None
    # A ZUGFeRD PDF shows its printed text to people: scan that as well as the XML.
    pdf = content if invoice.source_type is SourceType.PDF else None
    # The claim is committed and nothing is written yet, so the call (up to the validator
    # timeout) holds no row locks.
    return Reading(parsed, validator.validate(xml), injection=scan_injection(xml=xml, pdf=pdf))


def _extract(
    session: Session, storage: FileStorage, extractor: PdfExtractor, invoice: Invoice
) -> Reading | None:
    # The claim is committed, so the model calls (seconds each) hold no row locks.
    pdf = storage.read(invoice.storage_path)
    result = extractor.extract(pdf)
    session.add_all(
        ModelCall(
            invoice_id=invoice.id,
            at=call.at,
            purpose=EXTRACTION_PURPOSE,
            model=call.model,
            status=call.status,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            cost_usd=call.cost_usd,
            latency_ms=call.latency_ms,
            error=call.error,
        )
        for call in result.calls
    )
    # Committed on its own: the cost stays logged even if a later step fails.
    session.commit()
    summary = {
        "model": extractor.model,
        "calls": len(result.calls),
        "cost_usd": str(sum((call.cost_usd or Decimal(0) for call in result.calls), Decimal(0))),
    }
    if result.extraction is None:
        _finish(session, invoice, InvoiceStatus.FAILED, result.failure, extraction=summary)
        return None
    return Reading(
        result.extraction.invoice,
        NO_XML,
        result.extraction.confidences,
        extractor.confidence_threshold,
        {"extraction": summary},
        scan_injection(pdf=pdf),
    )


# --- Graph nodes --------------------------------------------------------------------------------


def _load(session: Session, state: RunState) -> Invoice:
    return session.get_one(Invoice, uuid.UUID(state["invoice_id"]))


def _reading_update(reading: Reading | None) -> RunState:
    return {"reading": None if reading is None else READING.dump_python(reading, mode="json")}


def _read_node(state: RunState, runtime: Runtime[Services]) -> RunState:
    services = runtime.context
    if services.validator is None:
        raise ValueError("A run that reads XML needs the KoSIT validator.")
    with services.session_factory() as session:
        invoice = _load(session, state)
        try:
            reading = _read_xml(
                session,
                services.storage,
                services.validator,
                services.extractor is not None,
                invoice,
            )
        except Exception:
            _fail_internal(session, invoice, "Processing")
            reading = None
    return _reading_update(reading)


def _extract_node(state: RunState, runtime: Runtime[Services]) -> RunState:
    services = runtime.context
    if services.extractor is None:
        raise ValueError("An extraction run needs the PDF extractor.")
    with services.session_factory() as session:
        invoice = _load(session, state)
        try:
            reading = _extract(session, services.storage, services.extractor, invoice)
        except Exception:
            _fail_internal(session, invoice, "Extracting")
            reading = None
    return _reading_update(reading)


def _checks_node(state: RunState, runtime: Runtime[Services]) -> RunState:
    reading = READING.validate_python(state["reading"])
    with runtime.context.session_factory() as session:
        invoice = _load(session, state)
        try:
            _check_and_finish(session, invoice, reading)
        except Exception:
            _fail_internal(session, invoice, "Checking")
    # The invoice data is stored in its tables now; the checkpoint need not keep a copy.
    return {"reading": None}


def _review_node(state: RunState) -> RunState:
    # The first statement: LangGraph runs a node again from its start when it resumes, so
    # nothing may happen here before the pause (ADR-015).
    decision: Decision = interrupt({"invoice_id": state["invoice_id"]})
    return {"decision": decision}


def _check_override_decider(session: Session, invoice: Invoice, decision: Decision) -> None:
    """Four eyes (ADR-016): only an approver, and never the requester, decides an override."""
    user = session.get(User, uuid.UUID(decision["user_id"]))
    if user is None or user.role is not UserRole.APPROVER:
        raise ForbiddenDecision(f"{decision['actor']} is not an approver")
    if override_requester(session, invoice.id) == user.id:
        raise ForbiddenDecision(f"{decision['actor']} requested this override")


def _decision_event(session: Session, invoice: Invoice, decision: Decision) -> AuditEvent:
    action = decision["action"]
    details: dict[str, Any] = {}
    if action in ("request_override", "confirm_override", "decline_override"):
        details["failed_checks"] = failed_checks(session, invoice.id)
    if decision.get("bookings"):
        details["bookings"] = decision["bookings"]
    return AuditEvent(
        actor=decision["actor"],
        user_id=uuid.UUID(decision["user_id"]),
        action=AUDIT_ACTION[action],
        entity_type="invoice",
        entity_id=str(invoice.id),
        status_before=invoice.status.value,
        status_after=NEW_STATUS[action].value,
        reason=decision["reason"],
        details=details,
    )


def _decide_node(state: RunState, runtime: Runtime[Services]) -> RunState:
    """The only place that writes a decision: the status and one audit row, one commit."""
    decision = state["decision"]
    with runtime.context.session_factory() as session:
        invoice = session.get(
            Invoice, uuid.UUID(state["invoice_id"]), with_for_update=True, populate_existing=True
        )
        if invoice is None or invoice.status.value != decision["status_before"]:
            raise StaleDecision(
                f"Invoice {state['invoice_id']} is no longer {decision['status_before']}"
            )
        if decision["action"] in ("confirm_override", "decline_override"):
            _check_override_decider(session, invoice, decision)
        if decision["action"] == "reopen":
            if invoice.status is not InvoiceStatus.REJECTED:
                raise ReopenRefused(f"Invoice {invoice.id} is {invoice.status.value}")
            # Read and checks write them again; until then nothing out of date is shown.
            session.execute(delete(InvoiceField).where(InvoiceField.invoice_id == invoice.id))
            session.execute(delete(Check).where(Check.invoice_id == invoice.id))
        session.add(_decision_event(session, invoice, decision))
        if decision["action"] in APPROVING:
            record_bookings(
                session, invoice.id, uuid.UUID(decision["user_id"]), decision.get("bookings", [])
            )
        invoice.status = NEW_STATUS[decision["action"]]
        invoice.status_reason = decision["reason"]
        session.commit()
        logger.info("Invoice %s is %s by %s", invoice.id, invoice.status.value, decision["actor"])
    return {}


def _after_decide(state: RunState) -> str:
    # A reopened invoice is read and checked again, then pauses at review.
    if state["decision"]["action"] == "reopen":
        return "read"
    # A decision that leaves the invoice in review (an override request waiting for the
    # approver, a declined override back in `blocked`) pauses the thread at review again.
    return "review" if NEW_STATUS[state["decision"]["action"]] in IN_REVIEW else END


def _start(state: RunState) -> Start:
    return state["start"]


def _after_reading(state: RunState) -> Literal["checks", "review"]:
    return "checks" if state.get("reading") is not None else "review"


def _build_graph() -> StateGraph[RunState, Services, RunState, RunState]:
    graph = StateGraph(RunState, context_schema=Services)
    graph.add_node("read", _read_node)
    graph.add_node("extract", _extract_node)
    graph.add_node("checks", _checks_node)
    graph.add_node("review", _review_node)
    graph.add_node("decide", _decide_node)
    graph.add_conditional_edges(START, _start, ["read", "extract", "review"])
    graph.add_conditional_edges("read", _after_reading, ["checks", "review"])
    graph.add_conditional_edges("extract", _after_reading, ["checks", "review"])
    graph.add_edge("checks", "review")
    graph.add_edge("review", "decide")
    graph.add_conditional_edges("decide", _after_decide, ["review", "read", END])
    return graph


GRAPH = _build_graph()
Graph = CompiledStateGraph[RunState, Services, RunState, RunState]


# --- Running threads ----------------------------------------------------------------------------


@contextmanager
def _open_graph(session_factory: sessionmaker[Session]) -> Iterator[Graph]:
    with open_checkpointer(engine_of(session_factory)) as checkpointer:
        yield GRAPH.compile(checkpointer=checkpointer)


def _config(invoice_id: uuid.UUID) -> RunnableConfig:
    return {"configurable": {"thread_id": str(invoice_id)}}


def _invoke(
    graph: Graph, services: Services, invoice_id: uuid.UUID, value: RunState | Command[Any]
) -> None:
    # "sync": each step's checkpoint is stored before the next step starts.
    graph.invoke(value, _config(invoice_id), context=services, durability="sync")


def _run(services: Services, invoice_id: uuid.UUID, start: Start) -> None:
    with _open_graph(services.session_factory) as graph:
        _invoke(graph, services, invoice_id, {"invoice_id": str(invoice_id), "start": start})


def paused_for_review(graph: Graph, invoice_id: uuid.UUID) -> bool:
    state = graph.get_state(_config(invoice_id))
    return state.next == ("review",) and any(task.interrupts for task in state.tasks)


def _pause_for_review(graph: Graph, services: Services, invoice_id: uuid.UUID) -> bool:
    """Start a run at review unless the thread is paused there; True if it started one.

    For invoices from before the graph (ADR-015), and for a thread whose last decision failed
    after it had resumed: the new run replaces that half-done one.
    """
    if paused_for_review(graph, invoice_id):
        return False
    _invoke(graph, services, invoice_id, {"invoice_id": str(invoice_id), "start": "review"})
    return True


def apply_decision(services: Services, invoice_id: uuid.UUID, decision: Decision) -> None:
    """Resume the invoice's thread with a reviewer's decision; decide writes the outcome.

    The caller holds the invoice lock and has checked the rules. If this raises, the status
    is unchanged (decide writes in one transaction) and the call can be repeated.
    """
    with _open_graph(services.session_factory) as graph:
        _pause_for_review(graph, services, invoice_id)
        _invoke(graph, services, invoice_id, Command(resume=decision))


def delete_threads(
    session_factory: sessionmaker[Session], invoice_ids: Iterable[uuid.UUID]
) -> None:
    """Delete the invoices' threads with all their checkpoints."""
    with open_checkpointer(engine_of(session_factory)) as checkpointer:
        for invoice_id in invoice_ids:
            checkpointer.delete_thread(str(invoice_id))


# --- Entry points -------------------------------------------------------------------------------


def process_invoice(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    validator: KositValidator,
    extractor: PdfExtractor | None,
    invoice_id: uuid.UUID,
    *,
    wait: bool = True,
) -> None:
    """Parse and check one `received` invoice; any error in the work ends in status `failed`.

    A plain PDF goes on to `extract_invoice` when an extractor is configured. If the database
    itself fails, the invoice stays `processing` and startup recovery resumes it. With
    `wait=False` (recovery) an invoice whose lock another session holds is skipped.
    """
    with invoice_lock(session_factory, invoice_id, wait=wait) as locked:
        if not locked:
            logger.info("Invoice %s is locked by another run; skipped", invoice_id)
            return
        with session_factory() as session:
            if not _claim(session, invoice_id, InvoiceStatus.RECEIVED):
                logger.info("Invoice %s is not waiting for processing; skipped", invoice_id)
                return
        _run(Services(session_factory, storage, validator, extractor), invoice_id, "read")
    awaiting = _status(session_factory, invoice_id) is InvoiceStatus.AWAITING_EXTRACTION
    if awaiting and extractor is not None:
        extract_invoice(session_factory, storage, extractor, invoice_id, wait=wait)


def spent_today_usd(session: Session) -> Decimal:
    """LLM cost logged since midnight UTC, for every purpose and invoice."""
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    spent: Decimal = session.scalar(
        select(func.coalesce(func.sum(ModelCall.cost_usd), 0)).where(ModelCall.at >= midnight)
    )
    return spent


def _defer_for_budget(session: Session, invoice_id: uuid.UUID, spent: Decimal) -> None:
    """Keep the invoice waiting and say why; the audit log records each deferral."""
    deferred = session.execute(
        update(Invoice)
        .where(Invoice.id == invoice_id, Invoice.status == InvoiceStatus.AWAITING_EXTRACTION)
        .values(status_reason=BUDGET_REASON)
        .returning(Invoice.id)
    ).scalar_one_or_none()
    if deferred is None:
        session.rollback()
        return
    session.add(
        AuditEvent(
            actor=SYSTEM_ACTOR,
            action="invoice.extraction_deferred",
            entity_type="invoice",
            entity_id=str(invoice_id),
            reason=BUDGET_REASON,
            details={"spent_today_usd": str(spent)},
        )
    )
    session.commit()
    logger.warning("Daily LLM budget used up (%s USD); invoice %s waits", spent, invoice_id)


def extract_invoice(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    extractor: PdfExtractor,
    invoice_id: uuid.UUID,
    *,
    wait: bool = True,
) -> None:
    """Extract and check an invoice in `awaiting_extraction`; any error ends in `failed`.

    With a daily budget, the invoice keeps waiting once today's logged cost has reached it. The
    check runs before the call, so parallel extractions can overshoot it by one invoice each.
    With `wait=False` (recovery) an invoice whose lock another session holds is skipped.
    """
    with invoice_lock(session_factory, invoice_id, wait=wait) as locked:
        if not locked:
            logger.info("Invoice %s is locked by another run; skipped", invoice_id)
            return
        with session_factory() as session:
            budget = extractor.daily_budget_usd
            if budget is not None and (spent := spent_today_usd(session)) >= budget:
                _defer_for_budget(session, invoice_id, spent)
                return
            if not _claim(session, invoice_id, InvoiceStatus.AWAITING_EXTRACTION):
                logger.info("Invoice %s is not waiting for extraction; skipped", invoice_id)
                return
        _run(Services(session_factory, storage, None, extractor), invoice_id, "extract")


def _waiting(session: Session, statuses: Iterable[InvoiceStatus]) -> list[uuid.UUID]:
    return list(
        session.scalars(
            select(Invoice.id)
            .where(Invoice.status.in_(list(statuses)))
            .order_by(Invoice.created_at, Invoice.id)
        ).all()
    )


def _pause_all_for_review(services: Services, invoice_ids: list[uuid.UUID]) -> int:
    """Make sure every given invoice still in review has a thread paused at review. An
    invoice another session holds is skipped: a decision pauses its thread itself."""
    paused = 0
    with _open_graph(services.session_factory) as graph:
        for invoice_id in invoice_ids:
            with invoice_lock(services.session_factory, invoice_id, wait=False) as locked:
                # A decision may have come in since the list was read.
                if locked and _status(services.session_factory, invoice_id) in IN_REVIEW:
                    paused += _pause_for_review(graph, services, invoice_id)
    return paused


def _reset_interrupted(session_factory: sessionmaker[Session]) -> int:
    """Reset `processing` invoices nobody works on to `received`; returns how many.

    A run holds the invoice's lock from its claim to its end, so a `processing` invoice whose
    lock is free was left behind by a stopped process. One whose lock is held is being worked
    on, maybe by another api pod, and is left alone.
    """
    with session_factory() as session:
        stuck = session.scalars(
            select(Invoice.id).where(Invoice.status == InvoiceStatus.PROCESSING)
        ).all()
    reset = 0
    for invoice_id in stuck:
        with session_factory() as session:
            if not try_lock_invoice(session, invoice_id):
                logger.info("Invoice %s is being processed elsewhere; not reset", invoice_id)
                continue
            changed = session.execute(
                update(Invoice)
                .where(Invoice.id == invoice_id, Invoice.status == InvoiceStatus.PROCESSING)
                .values(status=InvoiceStatus.RECEIVED, status_reason=RESTART_REASON)
                .returning(Invoice.id)
            ).scalar_one_or_none()
            if changed is not None:
                session.add(
                    _status_event(
                        invoice_id,
                        InvoiceStatus.PROCESSING,
                        InvoiceStatus.RECEIVED,
                        RESTART_REASON,
                    )
                )
                reset += 1
            # Also releases the lock.
            session.commit()
    return reset


def recover_unfinished(
    session_factory: sessionmaker[Session],
    storage: FileStorage,
    validator: KositValidator,
    extractor: PdfExtractor | None,
) -> None:
    """On startup: reset invoices a stopped process left in `processing`, pause every invoice
    in review whose thread is not paused at review, then process all `received` and, when an
    extractor is configured, extract all `awaiting_extraction`.

    Safe with several api pods starting at once (R4-2): every step only tries each invoice's
    lock and skips the invoices another pod holds, and the claim lets one run take an invoice.
    """
    if reset := _reset_interrupted(session_factory):
        logger.info("Reset %d invoice(s) interrupted by a stopped process", reset)
    with session_factory() as session:
        in_review = _waiting(session, IN_REVIEW)
        pending = _waiting(session, [InvoiceStatus.RECEIVED])
        # Read before processing `received`: those go on to extraction by themselves.
        awaiting = (
            [] if extractor is None else _waiting(session, [InvoiceStatus.AWAITING_EXTRACTION])
        )
    services = Services(session_factory, storage, validator, extractor)
    if in_review and (paused := _pause_all_for_review(services, in_review)):
        logger.info("Paused %d invoice(s) for review that had no paused thread", paused)
    if pending or awaiting:
        logger.info(
            "Resuming %d unfinished and %d awaiting-extraction invoice(s) after startup",
            len(pending),
            len(awaiting),
        )
    for invoice_id in pending:
        process_invoice(session_factory, storage, validator, extractor, invoice_id, wait=False)
    if extractor is not None:
        for invoice_id in awaiting:
            extract_invoice(session_factory, storage, extractor, invoice_id, wait=False)
