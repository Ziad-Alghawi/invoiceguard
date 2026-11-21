"""Prometheus metrics (R4-5, ADR-025), served at GET /metrics for the demo's Prometheus.

The metric objects live in this module; each app gets its own registry with them and its own
validator health check, so tests can create many apps. Counters are per process: Prometheus sums
the pods and handles restarts with rate() and increase().

Rows committed to the tables of record are counted in metrics_rows.py; the exception agent's
runs and the KoSIT calls where they end (agent/service.py, checks/kosit.py); HTTP requests in the
middleware below.

Labels are fixed vocabularies (routes, statuses, check types, models); never invoice data, ids
or user text.
"""

import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator

from fastapi import APIRouter, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    disable_created_metrics,
    generate_latest,
)
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# The `_created` series would double the series count for a timestamp nobody queries. The
# function has no annotations in prometheus-client 0.26.
disable_created_metrics()  # type: ignore[no-untyped-call]

# Probes and the scrape itself would drown the traffic the dashboard is for.
NOT_COUNTED_ROUTES = frozenset({"/metrics", "/health", "/ready"})
# A request no route matched (a 404, or a 413 before routing): one label, not one per path.
UNMATCHED_ROUTE = "unmatched"
VALIDATOR_HEALTH_PATH = "server/health"
VALIDATOR_HEALTH_TIMEOUT_SECONDS = 2.0

HTTP_REQUESTS = Counter(
    "invoiceguard_http_requests",
    "HTTP requests by method, route template and status code.",
    ["method", "route", "status"],
    registry=None,
)
HTTP_DURATION = Histogram(
    "invoiceguard_http_request_duration_seconds",
    "HTTP request duration by method and route template.",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    registry=None,
)
INVOICES_PROCESSED = Counter(
    "invoiceguard_invoices_processed",
    "Invoices that finished processing, by the status they ended in.",
    ["outcome"],
    registry=None,
)
CHECK_RESULTS = Counter(
    "invoiceguard_check_results",
    "Check results saved, by check type and status.",
    ["check", "status"],
    registry=None,
)
DECISIONS = Counter(
    "invoiceguard_decisions",
    "Review decisions, by action.",
    ["action"],
    registry=None,
)
SECURITY_EVENTS = Counter(
    "invoiceguard_security_events",
    "Security events written, by kind.",
    ["kind"],
    registry=None,
)
LLM_CALLS = Counter(
    "invoiceguard_llm_calls",
    "LLM calls, by purpose, model and status.",
    ["purpose", "model", "status"],
    registry=None,
)
LLM_COST = Counter(
    "invoiceguard_llm_cost_usd",
    "LLM cost in US dollars, as LiteLLM's price table.",
    ["purpose", "model"],
    registry=None,
)
LLM_TOKENS = Counter(
    "invoiceguard_llm_tokens",
    "LLM tokens, by purpose, model and direction (input or output).",
    ["purpose", "model", "direction"],
    registry=None,
)
LLM_LATENCY = Histogram(
    "invoiceguard_llm_latency_seconds",
    "LLM call latency, by purpose and model.",
    ["purpose", "model"],
    buckets=(0.5, 1, 2, 5, 10, 20, 40, 80),
    registry=None,
)
AGENT_RUNS = Counter(
    "invoiceguard_agent_runs",
    "Finished exception agent runs, by status and stop reason (none when completed).",
    ["status", "reason"],
    registry=None,
)
# The series behind the "cost cap reached" alert exist from the start at 0: increase() cannot see
# the first stop of a series that only appears with it.
for _reason in ("cost_cap", "daily_budget"):
    AGENT_RUNS.labels("stopped", _reason)
VALIDATOR_REQUESTS = Counter(
    "invoiceguard_validator_requests",
    "Calls to the KoSIT validator, by outcome.",
    ["outcome"],
    registry=None,
)
VALIDATOR_DURATION = Histogram(
    "invoiceguard_validator_duration_seconds",
    "KoSIT validator call duration, by outcome.",
    ["outcome"],
    buckets=(0.1, 0.25, 0.5, 1, 2, 5, 10, 20),
    registry=None,
)
_METRICS: tuple[Collector, ...] = (
    HTTP_REQUESTS,
    HTTP_DURATION,
    INVOICES_PROCESSED,
    CHECK_RESULTS,
    DECISIONS,
    SECURITY_EVENTS,
    LLM_CALLS,
    LLM_COST,
    LLM_TOKENS,
    LLM_LATENCY,
    AGENT_RUNS,
    VALIDATOR_REQUESTS,
    VALIDATOR_DURATION,
)


class ValidatorHealth(Collector):
    """invoiceguard_validator_up: 1 when the validator's health endpoint answers 200, checked at
    each scrape, so a down validator shows (and alerts) even when nobody uploads."""

    def __init__(self, validator_url: str | None) -> None:
        self.health_url = (
            None
            if validator_url is None
            else urllib.parse.urljoin(validator_url, VALIDATOR_HEALTH_PATH)
        )

    def collect(self) -> Iterator[Metric]:
        gauge = GaugeMetricFamily(
            "invoiceguard_validator_up",
            "1 if the KoSIT validator's health endpoint answers, else 0 (also if not configured).",
        )
        gauge.add_metric([], 1.0 if self._healthy() else 0.0)
        yield gauge

    def _healthy(self) -> bool:
        if self.health_url is None:
            return False
        try:
            # The URL comes from our settings, never from a request.
            with urllib.request.urlopen(
                self.health_url, timeout=VALIDATOR_HEALTH_TIMEOUT_SECONDS
            ) as response:
                return bool(response.status == 200)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            return False


def make_registry(validator_url: str | None) -> CollectorRegistry:
    registry = CollectorRegistry()
    for metric in _METRICS:
        registry.register(metric)
    registry.register(ValidatorHealth(validator_url))
    return registry


class HttpMetricsMiddleware:
    """Counts requests and their duration by route template (`/invoices/{invoice_id}`), so the
    number of series stays fixed whatever paths clients send."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def send_and_record_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_and_record_status)
        finally:
            # The router writes the matched route into the scope this middleware passed on.
            route = getattr(scope.get("route"), "path", UNMATCHED_ROUTE)
            if route not in NOT_COUNTED_ROUTES:
                method = scope["method"]
                HTTP_REQUESTS.labels(method, route, str(status)).inc()
                HTTP_DURATION.labels(method, route).observe(time.perf_counter() - started)


router = APIRouter(tags=["probes"])


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    """Prometheus text format. Reached only inside the cluster: the ingress exposes web, and web
    forwards fixed api paths only (ADR-025)."""
    registry: CollectorRegistry = request.app.state.metrics_registry
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
