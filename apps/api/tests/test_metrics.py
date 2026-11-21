"""GET /metrics (R4-5, ADR-025): the Prometheus text format, HTTP requests by route template, the
committed rows (processed invoices, check results, decisions, security events, model calls), and
no invoice data in any label. The counters are per process, so each test compares before and after.
"""

import time
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from typing import Any

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import Engine

from conftest import PROCESSING_TIMEOUT_SECONDS, FinishedInvoice, poll_until_done
from fakes import COST_USD, FakeLLMClient, reply_text
from invoiceguard_api.auth import SESSION_COOKIE
from invoiceguard_api.db import make_session_factory
from invoiceguard_api.main import create_app
from invoiceguard_api.metrics import make_registry
from invoiceguard_api.metrics_rows import count_committed_rows
from invoiceguard_api.models import SecurityEvent, SecuritySeverity, User
from invoiceguard_api.settings import Settings

Sample = Callable[..., float]
EXTRACTION_MODEL = "gemini/gemini-3.8-flash"


def sample_of(client: TestClient) -> Sample:
    """A sample's current value in this app's registry; 0 when the series does not exist yet."""
    registry: CollectorRegistry = client.app.state.metrics_registry  # type: ignore[attr-defined]

    def value(name: str, **labels: str) -> float:
        return registry.get_sample_value(name, labels) or 0.0

    return value


def eventually(read: Callable[[], float], expected: float) -> None:
    """Wait for a counter: processing and agent runs count in a background thread just after
    their commit, so a client polling the API can see the new status a moment before the count."""
    deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
    while read() != pytest.approx(expected):
        assert time.monotonic() < deadline, f"{read()} != {expected}"
        time.sleep(0.02)


def upload(client: TestClient, finished: FinishedInvoice, content: bytes) -> dict[str, Any]:
    response = client.post(
        "/invoices", files={"file": ("rechnung.xml", content, "application/xml")}
    )
    assert response.status_code == 202, response.text
    return finished(response.headers["location"])


def test_metrics_is_the_prometheus_text_format(anon_client: TestClient) -> None:
    response = anon_client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    families = {
        family.name: family.type for family in text_string_to_metric_families(response.text)
    }
    assert families["invoiceguard_http_requests"] == "counter"
    assert families["invoiceguard_http_request_duration_seconds"] == "histogram"
    assert families["invoiceguard_llm_cost_usd"] == "counter"
    # Tests run without a validator URL: not configured counts as down.
    assert families["invoiceguard_validator_up"] == "gauge"
    assert "invoiceguard_validator_up 0.0" in response.text
    assert "_created" not in response.text


def test_requests_are_counted_by_route_template(client: TestClient) -> None:
    sample = sample_of(client)
    route = {"method": "GET", "route": "/invoices/{invoice_id}", "status": "404"}
    unmatched = {"method": "GET", "route": "unmatched", "status": "404"}
    before = sample("invoiceguard_http_requests_total", **route)
    before_unmatched = sample("invoiceguard_http_requests_total", **unmatched)
    before_health = sample(
        "invoiceguard_http_requests_total", method="GET", route="/health", status="200"
    )

    client.get("/invoices/00000000-0000-0000-0000-000000000000")
    client.get("/no/such/path")
    client.get("/health")
    client.get("/metrics")

    assert sample("invoiceguard_http_requests_total", **route) == before + 1
    assert sample("invoiceguard_http_requests_total", **unmatched) == before_unmatched + 1
    assert (
        sample(
            "invoiceguard_http_request_duration_seconds_count",
            method="GET",
            route="/invoices/{invoice_id}",
        )
        >= 1
    )
    # Probes and scrapes are not counted.
    assert (
        sample("invoiceguard_http_requests_total", method="GET", route="/health", status="200")
        == before_health
    )
    assert "/no/such/path" not in client.get("/metrics").text


@pytest.mark.usefixtures("seeded")
def test_processing_counts_the_outcome_and_each_check(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes]
) -> None:
    sample = sample_of(client)
    before_ready = sample("invoiceguard_invoices_processed_total", outcome="ready")
    before_iban = sample("invoiceguard_check_results_total", check="iban", status="passed")
    before_kosit = sample("invoiceguard_check_results_total", check="kosit", status="skipped")

    detail = upload(client, finished, samples["ubl_xrechnung"])

    assert detail["status"] == "ready"
    eventually(
        lambda: sample("invoiceguard_invoices_processed_total", outcome="ready"), before_ready + 1
    )
    assert sample("invoiceguard_check_results_total", check="iban", status="passed") == (
        before_iban + 1
    )
    assert sample("invoiceguard_check_results_total", check="kosit", status="skipped") == (
        before_kosit + 1
    )


@pytest.mark.usefixtures("seeded")
def test_a_blocked_invoice_and_a_decision_are_counted(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes]
) -> None:
    sample = sample_of(client)
    before_blocked = sample("invoiceguard_invoices_processed_total", outcome="blocked")
    before_reject = sample("invoiceguard_decisions_total", action="reject")

    detail = upload(client, finished, samples["ubl_fraud_iban"])
    response = client.post(f"/invoices/{detail['id']}/reject", json={"reason": "Wrong IBAN."})

    assert response.status_code == 200, response.text
    eventually(
        lambda: sample("invoiceguard_invoices_processed_total", outcome="blocked"),
        before_blocked + 1,
    )
    assert sample("invoiceguard_decisions_total", action="reject") == before_reject + 1


def test_a_failed_login_is_a_security_event(anon_client: TestClient, reviewer: User) -> None:
    sample = sample_of(anon_client)
    before = sample("invoiceguard_security_events_total", kind="login_failed")

    wrong = "not-the-password"  # pragma: allowlist secret
    response = anon_client.post("/auth/login", json={"email": reviewer.email, "password": wrong})

    assert response.status_code == 401
    assert sample("invoiceguard_security_events_total", kind="login_failed") == before + 1


def test_a_rolled_back_row_is_not_counted(engine: Engine) -> None:
    session_factory = make_session_factory(engine)
    count_committed_rows(session_factory)
    registry = make_registry(None)

    def value() -> float:
        return registry.get_sample_value("invoiceguard_security_events_total", {"kind": "t"}) or 0.0

    before = value()
    with session_factory() as session:
        session.add(SecurityEvent(type="t", severity=SecuritySeverity.LOW, details={}))
        session.flush()
        session.rollback()
        assert value() == before
        session.add(SecurityEvent(type="t", severity=SecuritySeverity.LOW, details={}))
        session.commit()
    assert value() == before + 1


@pytest.fixture
def llm_client(
    settings: Settings, engine: Engine, session_token: str, seeded: None
) -> Iterator[TestClient]:
    """The app with the fake model (tests/fakes.py), logged in as the reviewer."""
    with ExitStack() as stack:
        app = create_app(settings, llm_client=FakeLLMClient(reply_text()))
        client = stack.enter_context(TestClient(app))
        client.cookies.set(SESSION_COOKIE, session_token)
        yield client


def test_model_calls_count_calls_cost_tokens_and_latency(
    llm_client: TestClient, samples: dict[str, bytes]
) -> None:
    sample = sample_of(llm_client)
    labels = {"purpose": "extraction", "model": EXTRACTION_MODEL}
    before_calls = sample("invoiceguard_llm_calls_total", status="ok", **labels)
    before_cost = sample("invoiceguard_llm_cost_usd_total", **labels)
    before_input = sample("invoiceguard_llm_tokens_total", direction="input", **labels)
    before_latency = sample("invoiceguard_llm_latency_seconds_count", **labels)

    response = llm_client.post(
        "/invoices", files={"file": ("rechnung.pdf", samples["text_pdf"], "application/pdf")}
    )
    assert response.status_code == 202, response.text
    detail = poll_until_done(
        llm_client,
        response.headers["location"],
        frozenset({"received", "processing", "awaiting_extraction"}),
    )

    assert detail["status"] == "ready"
    eventually(
        lambda: sample("invoiceguard_llm_calls_total", status="ok", **labels), before_calls + 1
    )
    assert sample("invoiceguard_llm_cost_usd_total", **labels) == pytest.approx(
        before_cost + float(COST_USD)
    )
    assert sample("invoiceguard_llm_tokens_total", direction="input", **labels) == (
        before_input + 1290
    )
    assert sample("invoiceguard_llm_latency_seconds_count", **labels) == before_latency + 1


@pytest.mark.usefixtures("seeded")
def test_no_invoice_data_in_the_metrics(
    client: TestClient, finished: FinishedInvoice, samples: dict[str, bytes]
) -> None:
    detail = upload(client, finished, samples["ubl_xrechnung"])
    client.get(f"/invoices/{detail['id']}")

    text = client.get("/metrics").text

    for value in (detail["id"], "2026-IT-0815", "Demo IT-Service", "DE999000033", "rechnung.xml"):
        assert value not in text
