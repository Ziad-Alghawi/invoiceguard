"""A fake model for the tests: replies built from the truth, so a test controls every value."""

import hashlib
import json
import random
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from invoiceguard_api.llm import (
    EmbeddingReply,
    EmbeddingTask,
    FilePart,
    LLMReply,
    ReasoningEffort,
    UserPart,
)
from invoiceguard_api.parsing import ParsedInvoice
from invoiceguard_api.parsing.fields import DOCUMENT_TERMS


def _field(value: object, confidence: float) -> dict[str, Any]:
    text = None if value is None else str(value)
    evidence = None if text is None else {"page": 1, "snippet": text[:200]}
    return {"value": text, "confidence": confidence, "evidence": evidence}


def reply_for(invoice: ParsedInvoice, confidence: float = 1.0, **wrong: str) -> str:
    """The extraction JSON a perfect model would return, with `wrong` terms replaced."""
    body: dict[str, Any] = {
        term: _field(wrong.get(term, getattr(invoice, term)), confidence) for term in DOCUMENT_TERMS
    }
    body["lines"] = [
        {
            **{k: None if v is None else str(v) for k, v in line.model_dump().items()},
            "confidence": confidence,
            "evidence": {"page": 1, "snippet": line.item_name},
        }
        for line in invoice.lines
    ]
    body["vat_breakdown"] = [
        {
            **{k: None if v is None else str(v) for k, v in row.model_dump().items()},
            "confidence": confidence,
            "evidence": None,
        }
        for row in invoice.vat_breakdown
    ]
    return json.dumps(body)


def fake_vector(text: str, dimensions: int) -> tuple[float, ...]:
    """The same numbers for the same text, unrelated numbers for different texts."""
    rng = random.Random(hashlib.sha256(text.encode()).digest())
    return tuple(rng.uniform(-1, 1) for _ in range(dimensions))


class FakeEmbeddings:
    """Embeddings without meaning: equal texts are similar (1.0), others are not."""

    def embed(
        self, *, model: str, texts: Sequence[str], dimensions: int, task: EmbeddingTask
    ) -> EmbeddingReply:
        vectors = tuple(fake_vector(text, dimensions) for text in texts)
        return EmbeddingReply(vectors, 4 * len(texts), Decimal("0.000001") * len(texts), 300)


class ScriptedModel(FakeEmbeddings):
    """Answers each call with the next reply text; an Exception item raises instead."""

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = replies

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
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return LLMReply(reply, 1000, 500, Decimal("0.005"), 9000)


class RoutingModel:
    """Extraction calls get the truth of the attached PDF (by its hash); every other call (the
    agent) gets `agent_reply`. For runs whose call order a test does not want to script."""

    def __init__(self, truths: dict[str, ParsedInvoice], agent_reply: str) -> None:
        self.truths = truths
        self.agent_reply = agent_reply
        self.calls = 0

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
        self.calls += 1
        files = [part for part in user if isinstance(part, FilePart)]
        if files:
            text = reply_for(self.truths[hashlib.sha256(files[0].data).hexdigest()])
        else:
            text = self.agent_reply
        return LLMReply(text, 1000, 500, Decimal("0.005"), 9000)
