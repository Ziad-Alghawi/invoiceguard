"""The `LLMClient` protocol: what application code may ask a model for, independent of provider.

A client reports facts (text, tokens, cost, latency); policy, such as treating an unknown price
as an error or retrying invalid output, stays in the calling code.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class FilePart:
    """A document the model reads directly, for example a PDF."""

    mime_type: str
    data: bytes


UserPart = TextPart | FilePart


@dataclass(frozen=True)
class LLMReply:
    text: str
    input_tokens: int
    output_tokens: int
    # None when the price table has no price for the model; callers must not treat it as zero.
    cost_usd: Decimal | None
    latency_ms: int


class LLMError(Exception):
    """The call failed (quota, key, timeout, provider error). The message is safe to show users."""

    def __init__(self, message: str, latency_ms: int) -> None:
        super().__init__(message)
        self.latency_ms = latency_ms


class LLMClient(Protocol):
    def structured(
        self,
        *,
        model: str,
        system: str,
        user: Sequence[UserPart],
        schema_name: str,
        schema: dict[str, Any],
    ) -> LLMReply:
        """Ask for one JSON answer that follows `schema`; raises LLMError if the call fails.

        The reply text is not validated here: the caller parses and checks it.
        """
        ...
