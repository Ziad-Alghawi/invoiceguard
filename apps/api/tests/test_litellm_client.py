"""The LiteLLM adapter (ADR-004), with LiteLLM's own `mock_response`: the real request building,
response parsing and price lookup run, but nothing goes over the network."""

import base64
import functools
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import litellm
import pytest
from litellm.exceptions import AuthenticationError, InternalServerError, Timeout
from litellm.utils import get_optional_params
from pydantic import SecretStr

from invoiceguard_api.llm import FilePart, LLMError, TextPart
from invoiceguard_api.llm.litellm_client import LiteLLMClient
from invoiceguard_api.main import make_extractor
from invoiceguard_api.settings import Settings

PDF = b"%PDF-1.7 test"
MODEL = "gemini/gemini-3.8-flash"
SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
# Not a real key; the mock never sends it anywhere.
FAKE_KEY = "test-key-not-real"  # pragma: allowlist secret


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Make every `litellm.completion` a mock call and collect its arguments."""
    calls: list[dict[str, Any]] = []
    real = litellm.completion

    def mocked(mock_response: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return real(mock_response=mock_response, **kwargs)

    def use(mock_response: Any) -> list[dict[str, Any]]:
        monkeypatch.setattr(litellm, "completion", functools.partial(mocked, mock_response))
        return calls

    return use


def ask(client: LiteLLMClient, model: str = MODEL) -> Any:
    return client.structured(
        model=model,
        system="system prompt",
        user=[TextPart("before"), FilePart("application/pdf", PDF), TextPart("after")],
        schema_name="test",
        schema=SCHEMA,
        reasoning_effort="low",
    )


def test_reply_has_text_usage_cost_and_latency(sent: Any) -> None:
    calls = sent('{"a": 1}')

    reply = ask(LiteLLMClient(FAKE_KEY, 30))

    assert reply.text == '{"a": 1}'
    # LiteLLM's mock usage: 10 prompt and 20 completion tokens, priced from the pinned table.
    assert (reply.input_tokens, reply.output_tokens) == (10, 20)
    price = litellm.model_cost[MODEL]
    expected = Decimal(
        str(10 * price["input_cost_per_token"] + 20 * price["output_cost_per_token"])
    )
    assert reply.cost_usd == expected.quantize(Decimal("0.000001"))
    assert reply.latency_ms >= 0
    assert len(calls) == 1


def test_request_carries_the_pdf_schema_reasoning_effort_and_no_retries(sent: Any) -> None:
    calls = sent('{"a": 1}')

    ask(LiteLLMClient(FAKE_KEY, 30))

    request = calls[0]
    system, user = request["messages"]
    assert system == {"role": "system", "content": "system prompt"}
    data_url = "data:application/pdf;base64," + base64.b64encode(PDF).decode()
    assert user == {
        "role": "user",
        "content": [
            {"type": "text", "text": "before"},
            {"type": "file", "file": {"file_data": data_url}},
            {"type": "text", "text": "after"},
        ],
    }
    assert request["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "test", "schema": SCHEMA},
    }
    assert (request["api_key"], request["timeout"], request["num_retries"]) == (FAKE_KEY, 30, 0)
    assert request["reasoning_effort"] == "low"


@pytest.mark.parametrize("effort", ["minimal", "low"])
def test_low_effort_is_gemini_thinking_level_low(effort: str) -> None:
    # The pinned price table marks Gemini 3.8 Flash as not supporting `minimal`, so LiteLLM sends
    # `low`, the lowest level (ADR-010). A LiteLLM upgrade that changes this must be noticed.
    params = get_optional_params(
        model="gemini-3.8-flash", custom_llm_provider="gemini", reasoning_effort=effort
    )

    assert params["thinkingConfig"]["thinkingLevel"] == "low"


def test_unknown_price_is_reported_as_none(sent: Any) -> None:
    sent('{"a": 1}')

    reply = ask(LiteLLMClient(FAKE_KEY, 30), model="gemini/no-such-model")

    assert reply.cost_usd is None


@pytest.mark.parametrize(
    ("error", "message"),
    [
        ("litellm.RateLimitError", "rate limit or quota is used up"),
        (AuthenticationError("bad key", "gemini", MODEL), "rejected the API key"),
        (Timeout("slow", MODEL, "gemini"), "timed out"),
        ("litellm.InternalServerError", "The LLM call failed; see the API logs."),
    ],
)
def test_provider_errors_become_llm_errors_with_safe_messages(
    sent: Any, error: Any, message: str
) -> None:
    sent(error)

    with pytest.raises(LLMError, match=message) as raised:
        ask(LiteLLMClient(FAKE_KEY, 30))

    assert raised.value.latency_ms >= 0
    assert FAKE_KEY not in str(raised.value)


def test_api_key_is_redacted_from_the_log(sent: Any, caplog: pytest.LogCaptureFixture) -> None:
    sent(InternalServerError(f"POST /v1/models?key={FAKE_KEY} failed", "gemini", MODEL))

    with pytest.raises(LLMError):
        ask(LiteLLMClient(FAKE_KEY, 30))

    assert "key=[redacted] failed" in caplog.text
    assert FAKE_KEY not in caplog.text


def test_price_table_is_the_pinned_local_copy() -> None:
    # In a fresh process without the variable (conftest sets it for the tests): our module must
    # set it before LiteLLM is imported, so LiteLLM never downloads prices at runtime (ADR-004).
    env = {k: v for k, v in os.environ.items() if k != "LITELLM_LOCAL_MODEL_COST_MAP"}
    code = (
        "import os, invoiceguard_api.llm.litellm_client as c; "
        "print(os.environ['LITELLM_LOCAL_MODEL_COST_MAP'], "
        "'gemini/gemini-3.8-flash' in c.litellm.model_cost)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    )
    assert result.stdout.split() == ["True", "True"]


def test_importing_litellm_does_not_load_a_dotenv_file(tmp_path: Path) -> None:
    # LiteLLM's default mode loads the nearest .env on import (with `python -c`: from the working
    # directory). Our module must switch that off, or a developer's real key leaks into settings.
    (tmp_path / ".env").write_text("INVOICEGUARD_DOTENV_PROBE=loaded\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "LITELLM_MODE"}
    code = (
        "import os, invoiceguard_api.llm.litellm_client; "
        "print(os.environ.get('INVOICEGUARD_DOTENV_PROBE'))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.split() == ["None"]


def test_extractor_needs_a_key(settings: Settings) -> None:
    assert make_extractor(settings, None) is None

    with_key = settings.model_copy(update={"llm_api_key": SecretStr(FAKE_KEY)})
    extractor = make_extractor(with_key, None)

    assert extractor is not None
    assert isinstance(extractor.client, LiteLLMClient)
    assert (extractor.model, extractor.confidence_threshold) == (MODEL, Decimal("0.8"))
    assert extractor.reasoning_effort == "low"
