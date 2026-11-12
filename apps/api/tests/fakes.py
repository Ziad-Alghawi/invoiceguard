"""A fake `LLMClient` that replays recorded model replies, so no test calls a real model.

The recorded replies in fixtures/llm/ have the shape Gemini returns for our schema; the values
match ubl_xrechnung.xml, so a sample extraction passes the checks against the demo seed.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from invoiceguard_api.llm import LLMError, LLMReply, UserPart

LLM_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "llm"
COST_USD = Decimal("0.000412")
INPUT_TOKENS = 1290
OUTPUT_TOKENS = 860
LATENCY_MS = 2400


def recorded(name: str = "demo_it_service") -> dict[str, Any]:
    reply: dict[str, Any] = json.loads((LLM_FIXTURES / f"{name}.json").read_text("utf-8"))
    return reply


def reply_text(**changes: Any) -> str:
    """The recorded reply as JSON, with top-level keys replaced or added."""
    return json.dumps({**recorded(), **changes})


def field(value: str | None, confidence: float = 0.98, snippet: str = "...") -> dict[str, Any]:
    evidence = None if value is None else {"page": 1, "snippet": snippet}
    return {"value": value, "confidence": confidence, "evidence": evidence}


@dataclass(frozen=True)
class Request:
    model: str
    system: str
    user: tuple[UserPart, ...]
    schema_name: str
    schema: dict[str, Any]


class FakeLLMClient:
    """Answers each call with the next reply: JSON text, or an LLMError to raise."""

    def __init__(self, *replies: str | LLMError, cost_usd: Decimal | None = COST_USD) -> None:
        self._replies = list(replies)
        self.cost_usd = cost_usd
        self.requests: list[Request] = []

    def structured(
        self,
        *,
        model: str,
        system: str,
        user: Sequence[UserPart],
        schema_name: str,
        schema: dict[str, Any],
    ) -> LLMReply:
        self.requests.append(Request(model, system, tuple(user), schema_name, schema))
        assert self._replies, "the test made more model calls than it recorded replies for"
        reply = self._replies.pop(0)
        if isinstance(reply, LLMError):
            raise reply
        return LLMReply(reply, INPUT_TOKENS, OUTPUT_TOKENS, self.cost_usd, LATENCY_MS)
