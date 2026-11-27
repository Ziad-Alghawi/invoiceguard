"""FastAPI application factory.

Run locally with: uv run uvicorn --factory invoiceguard_api.main:create_app --reload
The factory (instead of a module-level app) means importing this module does not read settings.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import AnyHttpUrl
from starlette.concurrency import run_in_threadpool
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from invoiceguard_api.agent.loop import ExceptionAgent, Limits
from invoiceguard_api.agent.schema import Server
from invoiceguard_api.agent.service import fail_interrupted
from invoiceguard_api.agent.tools import AgentTools, McpTools
from invoiceguard_api.auth import router as auth_router
from invoiceguard_api.body_limit import ContentLengthLimitMiddleware
from invoiceguard_api.booking.routes import router as bookings_router
from invoiceguard_api.checks import KositValidator
from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.exports import router as exports_router
from invoiceguard_api.extraction import PdfExtractor
from invoiceguard_api.health import router as health_router
from invoiceguard_api.investigations import router as investigations_router
from invoiceguard_api.invoices import router as invoices_router
from invoiceguard_api.llm import Embedder, LLMClient
from invoiceguard_api.logging import configure_logging
from invoiceguard_api.metrics import HttpMetricsMiddleware, make_registry
from invoiceguard_api.metrics import router as metrics_router
from invoiceguard_api.metrics_rows import count_committed_rows
from invoiceguard_api.processing import recover_unfinished
from invoiceguard_api.review import router as review_router
from invoiceguard_api.security_events import router as security_events_router
from invoiceguard_api.settings import Settings, get_settings
from invoiceguard_api.storage import FileStorage
from invoiceguard_api.visualization import Visualizer

logger = logging.getLogger(__name__)

# Room for the multipart boundaries and headers around the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def make_llm_client(settings: Settings, llm_client: LLMClient | None) -> LLMClient | None:
    """The given client (tests), a LiteLLM client when an API key is set, else None."""
    if llm_client is not None or settings.llm_api_key is None:
        return llm_client
    # Imported here: LiteLLM takes seconds to import and is not needed without a key.
    from invoiceguard_api.llm.litellm_client import LiteLLMClient

    return LiteLLMClient(settings.llm_api_key.get_secret_value(), settings.llm_timeout_seconds)


def make_embedder(settings: Settings, embedder: Embedder | None) -> Embedder | None:
    """The given embedder (tests, evals), a LiteLLM client when an API key is set, else None:
    booking suggestions then use the text match for lines without a stored vector (ADR-020)."""
    if embedder is not None or settings.llm_api_key is None:
        return embedder
    from invoiceguard_api.llm.litellm_client import LiteLLMClient

    return LiteLLMClient(settings.llm_api_key.get_secret_value(), settings.llm_timeout_seconds)


def make_extractor(settings: Settings, llm_client: LLMClient | None) -> PdfExtractor | None:
    """The PDF extractor, or None without an API key: plain PDFs then wait (ADR-010)."""
    llm_client = make_llm_client(settings, llm_client)
    if llm_client is None:
        logger.info("LLM extraction is off: INVOICEGUARD_LLM_API_KEY is not set")
        return None
    return PdfExtractor(
        llm_client,
        settings.extraction_model,
        settings.extraction_confidence_threshold,
        settings.extraction_reasoning_effort,
        settings.llm_daily_budget_usd,
    )


def make_agent(
    settings: Settings,
    llm_client: LLMClient | None,
    tools: AgentTools | None,
    embedder: Embedder | None = None,
) -> ExceptionAgent | None:
    """The exception agent (ADR-018), or None without a model or without the MCP servers: the
    "Investigate" button then shows a recorded run where there is one."""
    if llm_client is None:
        logger.info("The exception agent is off: no LLM API key")
        return None
    if tools is None:
        urls: dict[Server, AnyHttpUrl | None] = {
            "erp": settings.mcp_erp_url,
            "registry": settings.mcp_registry_url,
            "history": settings.mcp_history_url,
        }
        if any(url is None for url in urls.values()):
            logger.info("The exception agent is off: INVOICEGUARD_MCP_*_URL is not set")
            return None
        tools = McpTools(
            {server: str(url) for server, url in urls.items()}, settings.mcp_timeout_seconds
        )
    return ExceptionAgent(
        llm_client,
        tools,
        settings.agent_model or settings.extraction_model,
        settings.agent_reasoning_effort,
        Limits(
            settings.agent_max_steps,
            settings.agent_max_tool_calls,
            settings.agent_cost_cap_usd,
            settings.agent_timeout_seconds,
        ),
        settings.llm_daily_budget_usd,
        embedder=embedder,
        embedding_model=settings.embedding_model,
    )


def create_app(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
    agent_tools: AgentTools | None = None,
    embedder: Embedder | None = None,
) -> FastAPI:
    """`llm_client` replaces the LiteLLM client, `agent_tools` the MCP servers and `embedder`
    the embedding client, for tests with recorded model replies and fake tools. A given
    `llm_client` does not embed: without a key or an `embedder`, lines are not embedded."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    # The engine connects lazily, so creating the app does not need a running database.
    engine = make_engine(str(settings.database_url))
    session_factory = make_session_factory(engine)
    count_committed_rows(session_factory)
    storage = FileStorage(settings.storage_dir)
    validator_url = None if settings.validator_url is None else str(settings.validator_url)
    validator = KositValidator(validator_url, settings.validator_timeout_seconds)
    llm_client = make_llm_client(settings, llm_client)
    extractor = make_extractor(settings, llm_client)
    embedder = make_embedder(settings, embedder)
    agent = make_agent(settings, llm_client, agent_tools, embedder)

    def recover() -> None:
        try:
            if interrupted := fail_interrupted(session_factory):
                logger.info(
                    "Marked %d agent run(s) interrupted by a restart as failed", interrupted
                )
            recover_unfinished(session_factory, storage, validator, extractor)
        except Exception:
            # The API must still start (for example while the database is down); /ready reports it.
            logger.exception("Could not resume unfinished invoices on startup")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Runs in the thread pool next to request handling, so startup is not delayed (ADR-007).
        recovery = asyncio.create_task(run_in_threadpool(recover))
        yield
        await recovery
        engine.dispose()

    app = FastAPI(title="InvoiceGuard API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.storage = storage
    app.state.validator = validator
    app.state.visualizer = Visualizer(
        None if settings.visualization_url is None else str(settings.visualization_url),
        settings.visualization_timeout_seconds,
    )
    app.state.extractor = extractor
    app.state.agent = agent
    app.state.embedder = embedder
    app.state.metrics_registry = make_registry(validator_url)
    app.add_middleware(
        ContentLengthLimitMiddleware,
        max_bytes=settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES,
    )
    # Outside the body limit, so its 413s are counted too.
    app.add_middleware(HttpMetricsMiddleware)
    # Added last, so it runs first: the client address (per-IP login limit) comes from
    # X-Forwarded-For only when a trusted proxy connected. uvicorn's own handling of the header
    # is off (--no-proxy-headers in the Dockerfile), so this is the only place that reads it.
    if settings.trusted_proxies:
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=settings.trusted_proxies)
    app.include_router(health_router)
    app.include_router(metrics_router)
    app.include_router(auth_router)
    app.include_router(invoices_router)
    app.include_router(review_router)
    app.include_router(bookings_router)
    app.include_router(investigations_router)
    app.include_router(exports_router)
    app.include_router(security_events_router)
    return app
