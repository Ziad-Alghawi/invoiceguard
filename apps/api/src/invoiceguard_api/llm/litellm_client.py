"""`LLMClient` on the LiteLLM SDK (ADR-004), the only module that imports LiteLLM.

Importing LiteLLM takes seconds, so the app imports this module only when an API key is set.
"""

import base64
import logging
import os
import time
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

# Without this, importing LiteLLM downloads its price table from GitHub, so costs would come
# from whatever is on `main` today instead of the reviewed, pinned version (ADR-004).
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
# In its default "DEV" mode, importing LiteLLM loads the nearest .env file into the process
# environment (with API keys and anything else in it); our settings come only from real env vars.
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

import litellm
from litellm.exceptions import (
    LITELLM_EXCEPTION_TYPES,
    AuthenticationError,
    ModelNotMappedError,
    RateLimitError,
    Timeout,
)

from invoiceguard_api.llm.client import (
    LLMError,
    LLMReply,
    ReasoningEffort,
    TextPart,
    UserPart,
)

logger = logging.getLogger(__name__)

litellm.suppress_debug_info = True
_PROVIDER_ERRORS: tuple[type[Exception], ...] = tuple(LITELLM_EXCEPTION_TYPES)
# Six decimal places: a Flash call costs fractions of a cent.
COST_SCALE = Decimal("0.000001")


def _content(part: UserPart) -> dict[str, Any]:
    if isinstance(part, TextPart):
        return {"type": "text", "text": part.text}
    data = base64.b64encode(part.data).decode("ascii")
    return {"type": "file", "file": {"file_data": f"data:{part.mime_type};base64,{data}"}}


def _user_message(error: Exception) -> str:
    """A reason for the user; provider messages can echo request details, so they go to the log."""
    if isinstance(error, RateLimitError):
        return "The LLM provider's rate limit or quota is used up; try again later."
    if isinstance(error, AuthenticationError):
        return "The LLM provider rejected the API key (INVOICEGUARD_LLM_API_KEY)."
    if isinstance(error, Timeout):
        return "The LLM call timed out."
    return "The LLM call failed; see the API logs."


class LiteLLMClient:
    def __init__(self, api_key: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

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
        start = time.perf_counter()
        try:
            response = litellm.completion(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": [_content(part) for part in user]},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": schema},
                },
                reasoning_effort=reasoning_effort,
                api_key=self._api_key,
                timeout=self._timeout_seconds,
                # Retries are our decision (and each one is logged with its cost).
                num_retries=0,
            )
        except _PROVIDER_ERRORS as error:
            latency_ms = round((time.perf_counter() - start) * 1000)
            # Provider errors can quote the request URL, which for some providers holds the key.
            logged = str(error).replace(self._api_key, "[redacted]")
            logger.warning("LLM call to %s failed: %s: %s", model, type(error).__name__, logged)
            raise LLMError(_user_message(error), latency_ms) from error
        latency_ms = round((time.perf_counter() - start) * 1000)
        try:
            cost = Decimal(str(litellm.completion_cost(completion_response=response)))
            cost_usd: Decimal | None = cost.quantize(COST_SCALE)
        except ModelNotMappedError:
            cost_usd = None
        usage = response.usage
        return LLMReply(
            text=response.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )
