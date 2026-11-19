"""Calling the read-only MCP servers (ADR-017) for the exception agent.

`AgentTools` is what the loop needs; `McpTools` implements it with the MCP Python SDK's client
over streamable HTTP. The SDK is async and the app is sync (ADR-008), so each call runs its own
short event loop in the calling worker thread.
"""

import logging
from collections.abc import Sequence
from typing import Any, Protocol

import anyio
from mcp import Client

from invoiceguard_api.agent.schema import TOOLS, Server

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """The tool call failed: refused, invalid argument, server down. Safe to show the model."""


class AgentTools(Protocol):
    def call(
        self, tool: str, argument: str, query_vector: Sequence[float] | None = None
    ) -> dict[str, Any]:
        """The tool's structured result; raises ToolError if the call fails. `query_vector` is
        the api's embedding of the argument, for a tool that `embeds_query`."""
        ...


def arguments_for(tool: str, argument: str, query_vector: Sequence[float] | None) -> dict[str, Any]:
    """The MCP arguments of an allow-listed tool (raises ToolError for any other name): its one
    parameter, and the query vector (or null) for a tool that embeds its argument."""
    spec = TOOLS.get(tool)
    if spec is None:
        raise ToolError(f"Unknown tool {tool!r}.")
    arguments: dict[str, Any] = {spec.parameter: argument}
    if spec.embeds_query:
        arguments["query_vector"] = None if query_vector is None else list(query_vector)
    return arguments


class McpTools:
    def __init__(self, urls: dict[Server, str], timeout_seconds: float) -> None:
        self._urls = urls
        self._timeout_seconds = timeout_seconds

    async def _call(self, url: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with anyio.fail_after(self._timeout_seconds):
            async with Client(url, read_timeout_seconds=self._timeout_seconds) as client:
                result = await client.call_tool(tool, arguments)
        if result.is_error:
            texts = [getattr(block, "text", "") for block in result.content]
            raise ToolError(" ".join(text for text in texts if text)[:500] or "Tool error.")
        if not isinstance(result.structured_content, dict):
            raise ToolError("The tool returned no structured result.")
        return result.structured_content

    def call(
        self, tool: str, argument: str, query_vector: Sequence[float] | None = None
    ) -> dict[str, Any]:
        # The allow-list again, independent of the schema the model saw (ADR-018).
        arguments = arguments_for(tool, argument, query_vector)
        spec = TOOLS[tool]
        try:
            return anyio.run(self._call, self._urls[spec.server], tool, arguments)
        except ToolError:
            raise
        except TimeoutError as error:
            raise ToolError(f"The {spec.server} server did not answer in time.") from error
        except Exception as error:
            logger.warning("MCP call %s failed: %s: %s", tool, type(error).__name__, error)
            raise ToolError(f"The {spec.server} server could not be reached.") from error
