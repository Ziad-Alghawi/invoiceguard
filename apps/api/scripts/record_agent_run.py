"""Save a real exception-agent run as the recorded run the demo shows without a model key
(ADR-018).

Run a live investigation on the local stack first (model key in .env, `make dev`, upload a
blocked demo sample), then:

    uv run python scripts/record_agent_run.py <run id> <output.json>

with the output in src/invoiceguard_api/agent/recorded/.

The recording keeps the run's numbers (model, tokens, cost, duration, every step) and its case
key: the seller's VAT ID and the failed checks, so the same sample with another invoice number
matches. It reads INVOICEGUARD_DATABASE_URL.
"""

import argparse
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from invoiceguard_api.agent.service import case_key
from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.models import AgentRun, AgentRunSource, AgentRunStatus
from invoiceguard_api.settings import get_settings


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def recording(session: Session, run_id: uuid.UUID) -> dict[str, Any]:
    run = session.get_one(AgentRun, run_id)
    if run.status is not AgentRunStatus.COMPLETED or run.source is not AgentRunSource.LIVE:
        raise SystemExit(
            f"Run {run_id} is {run.source.value}/{run.status.value}, not a completed live run."
        )
    return {
        "scenario": case_key(session, run.invoice_id),
        "recorded_at": run.started_at.isoformat(),
        "model": run.model,
        "finding": run.finding,
        "email_subject": run.email_subject,
        "email_body": run.email_body,
        "input_tokens": run.input_tokens,
        "output_tokens": run.output_tokens,
        "cost_usd": _decimal(run.cost_usd),
        "duration_ms": run.duration_ms,
        "steps": [
            {
                "step_no": step.step_no,
                "kind": step.kind.value,
                "tool": step.tool,
                "argument": step.argument,
                "result": step.result,
                "input_tokens": step.input_tokens,
                "output_tokens": step.output_tokens,
                "cost_usd": _decimal(step.cost_usd),
                "latency_ms": step.latency_ms,
                "error": step.error,
            }
            for step in run.steps
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run_id", type=uuid.UUID)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    engine = make_engine(str(get_settings().database_url))
    try:
        with make_session_factory(engine)() as session:
            data = recording(session, args.run_id)
    finally:
        engine.dispose()
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(f"Wrote {args.output} ({data['scenario']})")


if __name__ == "__main__":
    main()
