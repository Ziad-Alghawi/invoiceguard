"""FastAPI application factory.

Run locally with: uv run uvicorn --factory invoiceguard_api.main:create_app --reload
The factory (instead of a module-level app) means importing this module does not read settings.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from invoiceguard_api.body_limit import ContentLengthLimitMiddleware
from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.health import router as health_router
from invoiceguard_api.invoices import router as invoices_router
from invoiceguard_api.logging import configure_logging
from invoiceguard_api.settings import Settings, get_settings
from invoiceguard_api.storage import FileStorage

# Room for the multipart boundaries and headers around the file itself.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    # The engine connects lazily, so creating the app does not need a running database.
    engine = make_engine(str(settings.database_url))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        engine.dispose()

    app = FastAPI(title="InvoiceGuard API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.storage = FileStorage(settings.storage_dir)
    app.add_middleware(
        ContentLengthLimitMiddleware,
        max_bytes=settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES,
    )
    app.include_router(health_router)
    app.include_router(invoices_router)
    return app
