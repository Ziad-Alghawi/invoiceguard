"""A recording `LLMClient` (ADR-019): replays saved model replies, and in live mode calls the
real client for requests it has no reply for and saves them.

The key is a SHA-256 over everything that shapes a reply: model, system prompt, schema, reasoning
effort, the user parts (files by their hash) and the run number. A changed prompt therefore misses
every recording and needs a live run; replay can never answer it with an old reply.

Database IDs are the one exception: the agent's case file and tool results carry UUIDs (a
supplier's ID in the IBAN check's evidence) that are new in every freshly created eval database,
so the key replaces each UUID with a placeholder. The reply was given for the same data.

Embeddings (ADR-020) are recorded per text, keyed by model, dimensions, task and the text, so a
text embedded once replays in any batch. A live batch's tokens and cost are split evenly over
its texts.
"""

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from invoiceguard_api.booking.history import decode_vector, encode_vector
from invoiceguard_api.llm import (
    Embedder,
    EmbeddingReply,
    EmbeddingTask,
    FilePart,
    LLMClient,
    LLMError,
    LLMReply,
    ReasoningEffort,
    UserPart,
)

# A live run's share of a batch's cost is kept to the nano-dollar.
SHARE_SCALE = Decimal("0.000000001")
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


def embedding_request(
    *, model: str, dimensions: int, task: EmbeddingTask, text: str
) -> dict[str, Any]:
    return {
        "kind": "embedding",
        "model": model,
        "dimensions": dimensions,
        "task": task,
        "text": text,
    }


class LiveClient(LLMClient, Embedder, Protocol):
    """What a live run calls: the LiteLLM client does both."""


@dataclass
class RecordingClient:
    directory: Path
    # The real client; None replays only.
    live: LiveClient | None = None
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

    def embed(
        self, *, model: str, texts: Sequence[str], dimensions: int, task: EmbeddingTask
    ) -> EmbeddingReply:
        keys = [
            request_key(embedding_request(model=model, dimensions=dimensions, task=task, text=t))
            for t in texts
        ]
        paths = [self.directory / f"{key}.json" for key in keys]
        missing = [index for index, path in enumerate(paths) if not path.exists()]
        if not missing:
            self.replayed += 1
        elif self.live is None and self.missing_as_failure:
            raise LLMError("No recorded embedding: the live call failed or was never made.", 0)
        elif self.live is None:
            raise MissingRecording(
                f"No recorded embedding for {len(missing)} text(s) with {model}; run with --live."
            )
        else:
            self._embed_live(
                model, dimensions, task, [texts[i] for i in missing], [paths[i] for i in missing]
            )
        records = [json.loads(path.read_text("utf-8"))["reply"] for path in paths]
        return EmbeddingReply(
            vectors=tuple(tuple(decode_vector(record["vector"])) for record in records),
            input_tokens=sum(record["input_tokens"] for record in records),
            cost_usd=sum((Decimal(record["cost_usd"]) for record in records), Decimal(0)),
            latency_ms=max(record["latency_ms"] for record in records),
        )

    def _embed_live(
        self,
        model: str,
        dimensions: int,
        task: EmbeddingTask,
        texts: list[str],
        paths: list[Path],
    ) -> None:
        assert self.live is not None
        if self.spent_usd >= self.max_spend_usd:
            raise SpendCapReached(
                f"Spent ${self.spent_usd} of the ${self.max_spend_usd} cap; stopping."
            )
        reply = self.live.embed(model=model, texts=texts, dimensions=dimensions, task=task)
        if reply.cost_usd is None or len(reply.vectors) != len(texts):
            raise LLMError("The embedding reply has no price or the wrong number of vectors.", 0)
        self.live_calls += 1
        self.spent_usd += reply.cost_usd
        share = (reply.cost_usd / len(texts)).quantize(SHARE_SCALE)
        recorded_at = datetime.now(UTC).isoformat(timespec="seconds")
        for text, path, vector in zip(texts, paths, reply.vectors, strict=True):
            record = {
                "recorded_at": recorded_at,
                "request": embedding_request(
                    model=model, dimensions=dimensions, task=task, text=text
                ),
                "reply": {
                    "vector": encode_vector(vector),
                    "input_tokens": round(reply.input_tokens / len(texts)),
                    "cost_usd": str(share),
                    "latency_ms": reply.latency_ms,
                },
            }
            _write(path, record)


def _write(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", "utf-8", newline="\n")


def _save(path: Path, description: dict[str, Any], reply: LLMReply) -> None:
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
    _write(path, record)


def _load(path: Path) -> LLMReply:
    reply = json.loads(path.read_text("utf-8"))["reply"]
    return LLMReply(
        text=reply["text"],
        input_tokens=reply["input_tokens"],
        output_tokens=reply["output_tokens"],
        cost_usd=None if reply["cost_usd"] is None else Decimal(reply["cost_usd"]),
        latency_ms=reply["latency_ms"],
    )
