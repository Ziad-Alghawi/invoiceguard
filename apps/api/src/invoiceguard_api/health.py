"""Liveness and readiness probes."""

import logging
from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from invoiceguard_api.db import ping

router = APIRouter(tags=["probes"])
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready", "unavailable"]


@router.get("/health")
def health() -> HealthResponse:
    """Liveness: the process is up and serving requests."""
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
def ready(request: Request, response: Response) -> ReadyResponse:
    """Readiness: the database answers a query."""
    try:
        ping(request.app.state.engine)
    except SQLAlchemyError:
        logger.warning("Readiness check failed: database unreachable", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(status="unavailable")
    return ReadyResponse(status="ready")
