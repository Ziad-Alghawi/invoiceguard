"""FastAPI application factory.

Run locally with: uv run uvicorn --factory invoiceguard_api.main:create_app --reload
The factory (instead of a module-level app) means importing this module does not read settings.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.concurrency import run_in_threadpool

from invoiceguard_api.agent.loop import ExceptionAgent, Limits
from invoiceguard_api.agent.service import fail_interrupted
from invoiceguard_api.agent.tools import AgentTools, McpTools
from invoiceguard_api.auth import router as auth_router
from invoiceguard_api.body_limit import ContentLengthLimitMiddleware
from invoiceguard_api.checks import KositValidator
from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.exports import router as exports_router
from invoiceguard_api.extraction import PdfExtractor
from invoiceguard_api.health import router as health_router
from invoiceguard_api.investigations import router as investigations_router
from invoiceguard_api.invoices import router as invoices_router
from invoiceguard_api.llm import LLMClient
from invoiceguard_api.logging import configure_logging
from invoiceguard_api.processing import recover_unfinished
from invoiceguard_api.review import router as review_router
from invoiceguard_api.security_events import router as security_events_router
from invoiceguard_api.settings import Settings, get_settings
from invoiceguard_api.storage import FileStorage

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
    settings: Settings, llm_client: LLMClient | None, tools: AgentTools | None
) -> ExceptionAgent | None:
    """The exception agent (ADR-018), or None without a model or without the MCP servers: the
    "Investigate" button then shows a recorded run where there is one."""
    if llm_client is None:
        logger.info("The exception agent is off: no LLM API key")
        return None
    if tools is None:
        if settings.mcp_erp_url is None or settings.mcp_registry_url is None:
            logger.info("The exception agent is off: INVOICEGUARD_MCP_*_URL is not set")
            return None
        tools = McpTools(
            {"erp": str(settings.mcp_erp_url), "registry": str(settings.mcp_registry_url)},
            settings.mcp_timeout_seconds,
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
    )


def create_app(
    settings: Settings | None = None,
    llm_client: LLMClient | None = None,
    agent_tools: AgentTools | None = None,
) -> FastAPI:
    """`llm_client` replaces the LiteLLM client and `agent_tools` the MCP servers, for tests
    with recorded model replies and fake tools."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    # The engine connects lazily, so creating the app does not need a running database.
    engine = make_engine(str(settings.database_url))
    session_factory = make_session_factory(engine)
    storage = FileStorage(settings.storage_dir)
    validator = KositValidator(
        None if settings.validator_url is None else str(settings.validator_url),
        settings.validator_timeout_seconds,
    )
    llm_client = make_llm_client(settings, llm_client)
    extractor = make_extractor(settings, llm_client)
    agent = make_agent(settings, llm_client, agent_tools)

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
    app.state.extractor = extractor
    app.state.agent = agent
    app.add_middleware(
        ContentLengthLimitMiddleware,
        max_bytes=settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES,
    )
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(invoices_router)
    app.include_router(review_router)
    app.include_router(investigations_router)
    app.include_router(exports_router)
    app.include_router(security_events_router)
    return app
