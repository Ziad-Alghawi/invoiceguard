"""The exception agent's investigation of an invoice (ADR-018): the latest run with every step,
and the "Investigate" action. The agent only proposes; nothing here changes the invoice.

- With a model key and the MCP servers, `POST /invoices/{id}/investigate` starts a live run in
  the background; poll `GET /invoices/{id}/investigation` until it is no longer `running`.
- Without them (the public demo), it stores the recorded run for the same case, if there is one.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from invoiceguard_api.agent.loop import ExceptionAgent
from invoiceguard_api.agent.service import (
    AlreadyRunning,
    latest_run,
    load_recorded,
    recording_for,
    refusal,
    run_investigation,
    start_run,
)
from invoiceguard_api.auth import CurrentUser, current_user
from invoiceguard_api.db import DbSession
from invoiceguard_api.invoices import ErrorOut, get_invoice_or_404
from invoiceguard_api.models import (
    AgentRun,
    AgentRunSource,
    AgentRunStatus,
    AgentStepKind,
    Invoice,
)

router = APIRouter(
    prefix="/invoices", tags=["investigations"], dependencies=[Depends(current_user)]
)

Mode = Literal["live", "recorded", "unavailable"]
ALREADY_RUNNING = "An investigation of this invoice is already running."
UNAVAILABLE = (
    "The exception agent is not configured here (no model key or MCP servers), and there is no "
    "recorded investigation for this case."
)


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    step_no: int
    kind: AgentStepKind
    tool: str | None
    argument: str | None
    result: dict[str, Any] | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    latency_ms: int
    error: str | None
    at: datetime


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: AgentRunStatus
    source: AgentRunSource
    stop_reason: str | None
    error: str | None
    model: str
    # English, for the reviewer.
    finding: str | None
    # From the supplier master data.
    email_to: str | None
    # German draft; nothing is sent.
    email_subject: str | None
    email_body: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    # Recorded runs: when the original run happened.
    recorded_at: datetime | None
    steps: list[StepOut]


class InvestigationOut(BaseModel):
    # The latest run, or null if the invoice was never investigated.
    run: RunOut | None
    # live: a model runs now; recorded: a saved run is shown; unavailable: neither.
    mode: Mode
    can_investigate: bool
    # Why the invoice cannot be investigated now, for the reviewer.
    reason: str | None


def _mode(request: Request, session: Session, invoice_id: uuid.UUID) -> Mode:
    if request.app.state.agent is not None:
        return "live"
    return "recorded" if recording_for(session, invoice_id) is not None else "unavailable"


def _investigation(
    request: Request, session: Session, invoice: Invoice, run: AgentRun | None
) -> InvestigationOut:
    mode = _mode(request, session, invoice.id)
    reason = refusal(session, invoice)
    if reason is None and run is not None and run.status is AgentRunStatus.RUNNING:
        reason = ALREADY_RUNNING
    if reason is None and mode == "unavailable":
        reason = UNAVAILABLE
    return InvestigationOut(
        run=None if run is None else RunOut.model_validate(run),
        mode=mode,
        can_investigate=reason is None,
        reason=reason,
    )


@router.get(
    "/{invoice_id}/investigation",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Unknown invoice"}},
)
def get_investigation(
    invoice_id: uuid.UUID, session: DbSession, request: Request
) -> InvestigationOut:
    """The latest investigation with every step, and whether the invoice can be investigated."""
    invoice = get_invoice_or_404(session, invoice_id)
    return _investigation(request, session, invoice, latest_run(session, invoice_id))


@router.post(
    "/{invoice_id}/investigate",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Unknown invoice"},
        status.HTTP_409_CONFLICT: {
            "model": ErrorOut,
            "description": "Not blocked, injection suspected, already running, or unavailable",
        },
    },
)
def investigate(
    invoice_id: uuid.UUID,
    session: DbSession,
    user: CurrentUser,
    request: Request,
    background_tasks: BackgroundTasks,
) -> InvestigationOut:
    """Investigate a blocked invoice: start a live run (poll the investigation until it is no
    longer `running`) or, without a model, load the recorded run for this case."""
    invoice = get_invoice_or_404(session, invoice_id)
    if (reason := refusal(session, invoice)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, reason)
    agent: ExceptionAgent | None = request.app.state.agent
    if agent is None:
        recording = recording_for(session, invoice_id)
        if recording is None:
            raise HTTPException(status.HTTP_409_CONFLICT, UNAVAILABLE)
        run = load_recorded(session, invoice_id, recording, user.id)
    else:
        try:
            run = start_run(session, invoice_id, agent.model, user.id)
        except AlreadyRunning:
            raise HTTPException(status.HTTP_409_CONFLICT, ALREADY_RUNNING) from None
        background_tasks.add_task(
            run_investigation, request.app.state.session_factory, agent, run.id
        )
    session.refresh(run)
    return _investigation(request, session, invoice, run)
