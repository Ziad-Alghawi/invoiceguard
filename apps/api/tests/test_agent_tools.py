"""`McpTools`: the allow-list is checked again before any MCP call, the one argument goes to the
tool's parameter on the right server, and every failure becomes a ToolError for the model.

The MCP SDK client is replaced by a fake; the servers themselves are tested in apps/mcp-*.
"""

from types import SimpleNamespace, TracebackType
from typing import Any, ClassVar

import anyio
import pytest

from invoiceguard_api.agent import tools as tools_module
from invoiceguard_api.agent.tools import McpTools, ToolError

# Fictitious (fake bank code), as in ubl_fraud_iban.xml; not a secret.
FRAUD_IBAN = "DE58876543210000000099"  # pragma: allowlist secret
URLS: dict[Any, str] = {
    "erp": "http://mcp-erp:8000/mcp",
    "registry": "http://mcp-registry:8000/mcp",
}


class FakeClient:
    calls: ClassVar[list[tuple[str, str, dict[str, str]]]] = []
    result: ClassVar[Any] = None
    error: ClassVar[Exception | None] = None
    delay: ClassVar[float] = 0.0

    def __init__(self, url: str, read_timeout_seconds: float) -> None:
        self.url = url

    async def __aenter__(self) -> "FakeClient":
        if FakeClient.error is not None:
            raise FakeClient.error
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        return None

    async def call_tool(self, tool: str, arguments: dict[str, str]) -> Any:
        FakeClient.calls.append((self.url, tool, arguments))
        await anyio.sleep(FakeClient.delay)
        return FakeClient.result


@pytest.fixture(autouse=True)
def fake_client(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.calls = []
    FakeClient.result = SimpleNamespace(is_error=False, content=[], structured_content={"ok": 1})
    FakeClient.error = None
    FakeClient.delay = 0.0
    monkeypatch.setattr(tools_module, "Client", FakeClient)


def test_calls_the_tool_on_its_server_with_its_parameter() -> None:
    tools = McpTools(URLS, timeout_seconds=5)

    assert tools.call("check_iban", FRAUD_IBAN) == {"ok": 1}
    assert tools.call("get_goods_receipts", "PO-2026-0004") == {"ok": 1}

    assert FakeClient.calls == [
        (URLS["registry"], "check_iban", {"iban": FRAUD_IBAN}),
        (URLS["erp"], "get_goods_receipts", {"po_number": "PO-2026-0004"}),
    ]


@pytest.mark.parametrize("tool", ["approve_invoice", "update_supplier", "execute_sql"])
def test_refuses_tools_outside_the_allow_list(tool: str) -> None:
    with pytest.raises(ToolError, match="Unknown tool"):
        McpTools(URLS, timeout_seconds=5).call(tool, "x")
    assert FakeClient.calls == []


def test_tool_error_text_reaches_the_model() -> None:
    FakeClient.result = SimpleNamespace(
        is_error=True,
        content=[SimpleNamespace(text="Input should match pattern")],
        structured_content=None,
    )
    with pytest.raises(ToolError, match="Input should match pattern"):
        McpTools(URLS, timeout_seconds=5).call("get_supplier", "nope")


def test_result_without_structured_content_is_an_error() -> None:
    FakeClient.result = SimpleNamespace(is_error=False, content=[], structured_content=None)
    with pytest.raises(ToolError, match="no structured result"):
        McpTools(URLS, timeout_seconds=5).call("get_supplier", "DE999000033")


def test_unreachable_server() -> None:
    FakeClient.error = OSError("connection refused")
    with pytest.raises(ToolError, match="erp server could not be reached"):
        McpTools(URLS, timeout_seconds=5).call("get_supplier", "DE999000033")


def test_slow_server_times_out() -> None:
    FakeClient.delay = 1.0
    with pytest.raises(ToolError, match="did not answer in time"):
        McpTools(URLS, timeout_seconds=0.05).call("check_vat_id", "DE999000033")
