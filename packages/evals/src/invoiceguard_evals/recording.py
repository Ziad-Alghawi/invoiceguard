"""A recording `LLMClient` (ADR-019): replays saved model replies, and in live mode calls the
real client for requests it has no reply for and saves them.

The key is a SHA-256 over everything that shapes a reply: model, system prompt, schema, reasoning
effort, the user parts (files by their hash) and the run number. A changed prompt therefore misses
every recording and needs a live run; replay can never answer it with an old reply.

Database IDs are the one exception: the agent's case file and tool results carry UUIDs (a
supplier's ID in the IBAN check's evidence) that are new in every freshly created eval database,
so the key replaces each UUID with a placeholder. The reply was given for the same data.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from invoiceguard_api.llm import FilePart, LLMClient, LLMError, LLMReply, ReasoningEffort, UserPart

UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")


class MissingRecording(Exception):
    """Replay found no saved reply: the request changed, or it was never recorded."""


class SpendCapReached(Exception):
    """A live run has spent its cap; the next call is not made."""


def _part(part: UserPart) -> dict[str, str]:
    if isinstance(part, FilePart):
        return {"file": part.mime_type, "sha256": hashlib.sha256(part.data).hexdigest()}
    return {"text": UUID.sub("<uuid>", part.text)}


def request(
    *,
    model: str,
    system: str,
    user: Sequence[UserPart],
    schema_name: str,
    schema: dict[str, Any],
    reasoning_effort: ReasoningEffort | None,
    run: int,
) -> dict[str, Any]:
    """The request as stored next to its reply: readable, but without the file bytes."""
    return {
        "model": model,
        "reasoning_effort": reasoning_effort,
        "run": run,
        "schema_name": schema_name,
        "schema_sha256": hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
        "system_sha256": hashlib.sha256(system.encode()).hexdigest(),
        "user": [_part(part) for part in user],
    }


def request_key(description: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(description, sort_keys=True).encode()).hexdigest()


@dataclass
class RecordingClient:
    directory: Path
    # The real client; None replays only.
    live: LLMClient | None = None
    max_spend_usd: Decimal = Decimal(0)
    # Repeated runs of the same request are separate recordings.
    run: int = 1
    # Replay only: answer a missing recording like a failed call. A live call that failed
    # (quota, timeout) is never recorded, so this reproduces a live run's report exactly.
    missing_as_failure: bool = False
    spent_usd: Decimal = Decimal(0)
    live_calls: int = 0
    replayed: int = 0

    def structured(
        self,
        *,
        model: str,
        system: str,
        user: Sequence[UserPart],
        schema_name: str,
        schema: dict[str, Any],
        reasoning_effort: ReasoningEffort | None = None,
    ) -> LLMReply:
        description = request(
            model=model,
            system=system,
            user=user,
            schema_name=schema_name,
            schema=schema,
            reasoning_effort=reasoning_effort,
            run=self.run,
        )
        path = self.directory / f"{request_key(description)}.json"
        if path.exists():
            self.replayed += 1
            return _load(path)
        if self.live is None and self.missing_as_failure:
            raise LLMError("No recorded reply: the live call failed or was never made.", 0)
        if self.live is None:
            raise MissingRecording(
                f"No recorded reply for {model} at reasoning effort {reasoning_effort} "
                f"(run {self.run}); the prompt, schema or file changed. Run with --live."
            )
        if self.spent_usd >= self.max_spend_usd:
            raise SpendCapReached(
                f"Spent ${self.spent_usd} of the ${self.max_spend_usd} cap; stopping."
            )
        # A failed call raises LLMError here and is never recorded.
        reply = self.live.structured(
            model=model,
            system=system,
            user=user,
            schema_name=schema_name,
            schema=schema,
            reasoning_effort=reasoning_effort,
        )
        self.live_calls += 1
        self.spent_usd += reply.cost_usd or Decimal(0)
        _save(path, description, reply)
        return reply


def _save(path: Path, description: dict[str, Any], reply: LLMReply) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "request": description,
        "reply": {
            "text": reply.text,
            "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens,
            "cost_usd": None if reply.cost_usd is None else str(reply.cost_usd),
            "latency_ms": reply.latency_ms,
        },
    }
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", "utf-8", newline="\n")


def _load(path: Path) -> LLMReply:
    reply = json.loads(path.read_text("utf-8"))["reply"]
    return LLMReply(
        text=reply["text"],
        input_tokens=reply["input_tokens"],
        output_tokens=reply["output_tokens"],
        cost_usd=None if reply["cost_usd"] is None else Decimal(reply["cost_usd"]),
        latency_ms=reply["latency_ms"],
    )
