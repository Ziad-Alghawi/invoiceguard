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

from invoiceguard_api.body_limit import ContentLengthLimitMiddleware
from invoiceguard_api.checks import KositValidator
from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.extraction import PdfExtractor
from invoiceguard_api.health import router as health_router
from invoiceguard_api.invoices import router as invoices_router
from invoiceguard_api.llm import LLMClient
from invoiceguard_api.logging import configure_logging
from invoiceguard_api.processing import recover_unfinished
from invoiceguard_api.settings import Settings, get_settings
from invoiceguard_api.storage import FileStorage

logger = logging.getLogger(__name__)

# Room for the multipart boundaries and headers around the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def make_extractor(settings: Settings, llm_client: LLMClient | None) -> PdfExtractor | None:
    """The PDF extractor, or None without an API key: plain PDFs then wait (ADR-010)."""
    if llm_client is None:
        if settings.llm_api_key is None:
            logger.info("LLM extraction is off: INVOICEGUARD_LLM_API_KEY is not set")
            return None
        # Imported here: LiteLLM takes seconds to import and is not needed without a key.
        from invoiceguard_api.llm.litellm_client import LiteLLMClient

        llm_client = LiteLLMClient(
            settings.llm_api_key.get_secret_value(), settings.llm_timeout_seconds
        )
    return PdfExtractor(
        llm_client,
        settings.extraction_model,
        settings.extraction_confidence_threshold,
        settings.extraction_reasoning_effort,
    )


def create_app(settings: Settings | None = None, llm_client: LLMClient | None = None) -> FastAPI:
    """`llm_client` replaces the LiteLLM client, for tests with recorded model replies."""
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
    extractor = make_extractor(settings, llm_client)

    def recover() -> None:
        try:
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
    app.add_middleware(
        ContentLengthLimitMiddleware,
        max_bytes=settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES,
    )
    app.include_router(health_router)
    app.include_router(invoices_router)
    return app
