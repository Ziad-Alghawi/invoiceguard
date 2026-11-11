"""Liveness and readiness probes."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["probes"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


class ReadyResponse(BaseModel):
    status: Literal["ready"]


@router.get("/health")
def health() -> HealthResponse:
    """Liveness: the process is up and serving requests."""
    return HealthResponse(status="ok")


@router.get("/ready")
def ready() -> ReadyResponse:
    """Readiness: dependencies are reachable. There are no dependencies yet."""
    return ReadyResponse(status="ready")
