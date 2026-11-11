"""FastAPI application factory.

Run locally with: uv run uvicorn invoiceguard_api.main:app --reload
"""

from fastapi import FastAPI

from invoiceguard_api.health import router as health_router
from invoiceguard_api.logging import configure_logging
from invoiceguard_api.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="InvoiceGuard API", version="0.1.0")
    app.include_router(health_router)
    return app


app = create_app()
