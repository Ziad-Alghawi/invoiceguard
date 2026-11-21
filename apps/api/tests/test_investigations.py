"""The exception agent in the app (ADR-018), on the seeded demo data and a real database, with a
fake model and fake tools: blocked invoices are investigated, every step is saved with its cost,
the agent never changes the invoice, injected invoices never reach the model, and without a model
the recorded run for the case is shown."""

import json
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import replace
from decimal import Decimal
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from conftest import FIXTURES, PROCESSING_TIMEOUT_SECONDS, poll_until_done
from fakes import COST_USD, FakeLLMClient, KeywordEmbedder
from invoiceguard_api import processing
from invoiceguard_api.agent import service
from invoiceguard_api.agent.schema import TOOLS
from invoiceguard_api.auth import SESSION_COOKIE
from invoiceguard_api.db import make_session_factory
from invoiceguard_api.demo import SAMPLES
from invoiceguard_api.main import create_app
from invoiceguard_api.models import (
    AgentRun,
    AuditEvent,
    Invoice,
    InvoiceStatus,
    ModelCall,
    ModelCallStatus,
)
from invoiceguard_api.seed import SUPPLIERS
from invoiceguard_api.settings import Settings
from test_agent_loop import FINDING, FRAUD_IBAN, FakeTools, call_tools, finish
from test_metrics import eventually, sample_of

StartApp = Callable[..., TestClient]
IT_SERVICE_CONTACT = "buchhaltung@demo-it-service.example"


@pytest.fixture
def start_app(
    settings: Settings, engine: Engine, session_token: str, seeded: None
) -> Iterator[StartApp]:
    """Start the app with a fake model and fake tools (or none: no model key), logged in as
    the reviewer; stopped after the test."""
    with ExitStack() as stack:

        def start(
            llm: FakeLLMClient | None = None,
            tools: FakeTools | None = None,
            embedder: KeywordEmbedder | None = None,
            **changes: Any,
        ) -> TestClient:
            app = create_app(
                settings.model_copy(update=changes),
                llm_client=llm,
                agent_tools=tools,
                embedder=embedder,
            )
            client = stack.enter_context(TestClient(app))
            client.cookies.set(SESSION_COOKIE, session_token)
            return client

        yield start


def upload(client: TestClient, name: str, content: bytes) -> dict[str, Any]:
    response = client.post("/invoices", files={"file": (name, content, "application/xml")})
    assert response.status_code == 202, response.text
    return poll_until_done(client, response.headers["location"])


def upload_fraud(client: TestClient) -> dict[str, Any]:
    detail = upload(client, "fraud.xml", (FIXTURES / "ubl_fraud_iban.xml").read_bytes())
    assert detail["status"] == "blocked"
    return detail


def investigation(client: TestClient, invoice_id: str) -> dict[str, Any]:
    """GET the investigation until its run is no longer running, as the UI polls it."""
    deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
    while True:
        body: dict[str, Any] = client.get(f"/invoices/{invoice_id}/investigation").json()
        if body["run"] is None or body["run"]["status"] != "running":
            return body
        assert time.monotonic() < deadline, "the investigation is still running"
        time.sleep(0.02)


def audit_actions(engine: Engine, invoice_id: str) -> list[str]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.entity_id == invoice_id)
                .order_by(AuditEvent.id)
            )
        )


def paused(engine: Engine, invoice_id: str) -> bool:
    with processing._open_graph(make_session_factory(engine)) as graph:
        return processing.paused_for_review(graph, uuid.UUID(invoice_id))


def test_a_blocked_invoice_is_investigated_after_processing(
    start_app: StartApp, engine: Engine
) -> None:
    llm = FakeLLMClient(call_tools(("check_iban", FRAUD_IBAN)), finish())
    tools = FakeTools({"check_iban": {"iban": FRAUD_IBAN, "registered_to": []}})
    client = start_app(llm, tools)

    invoice_id = upload_fraud(client)["id"]
    body = investigation(client, invoice_id)

    run = body["run"]
    assert (run["status"], run["source"]) == ("completed", "live")
    assert run["finding"] == FINDING
    assert run["email_subject"].startswith("Rückfrage")
    # From the master data, not the invoice.
    assert run["email_to"] == IT_SERVICE_CONTACT
    assert [(s["kind"], s["tool"]) for s in run["steps"]] == [
        ("model", None),
        ("tool", "check_iban"),
        ("model", None),
    ]
    assert Decimal(run["cost_usd"]) == 2 * COST_USD
    assert run["input_tokens"] > 0 and run["duration_ms"] is not None
    # The invoice data reached the model as untrusted data, the IBAN among it.
    assert FRAUD_IBAN in llm.requests[0].user[1].text  # type: ignore[union-attr]
    with Session(engine) as session:
        calls = session.scalars(select(ModelCall).where(ModelCall.purpose == "agent")).all()
    assert [(c.status, c.cost_usd) for c in calls] == [(ModelCallStatus.OK, COST_USD)] * 2
    assert {str(c.invoice_id) for c in calls} == {invoice_id}
    detail = client.get(f"/invoices/{invoice_id}").json()
    assert detail["llm_calls"] == 2


def test_a_rulebook_question_is_an_agent_cost(start_app: StartApp, engine: Engine) -> None:
    llm = FakeLLMClient(call_tools(("search_rulebook", "How to resolve a changed IBAN?")), finish())
    tools = FakeTools({"search_rulebook": {"method": "vector", "sections": []}})
    embedding_cost = Decimal("0.000004")
    client = start_app(llm, tools, KeywordEmbedder({"iban": 0}, cost_usd=embedding_cost))

    invoice_id = upload_fraud(client)["id"]
    run = investigation(client, invoice_id)["run"]

    assert run["status"] == "completed"
    tool_step = run["steps"][1]
    assert (tool_step["tool"], tool_step["cost_usd"]) == ("search_rulebook", str(embedding_cost))
    assert Decimal(run["cost_usd"]) == 2 * COST_USD + embedding_cost
    assert tools.vectors[0] is not None
    with Session(engine) as session:
        calls = session.scalars(
            select(ModelCall).where(ModelCall.purpose == "agent").order_by(ModelCall.at)
        ).all()
    assert {c.status for c in calls} == {ModelCallStatus.OK}
    assert sorted(str(c.cost_usd) for c in calls) == sorted(
        [str(COST_USD), str(COST_USD), str(embedding_cost)]
    )
    assert "gemini/gemini-embedding-001" in {c.model for c in calls}


def test_similar_invoices_are_searched_for_the_investigated_invoice(
    start_app: StartApp,
) -> None:
    llm = FakeLLMClient(call_tools(("search_similar_invoices", "current")), finish())
    tools = FakeTools({"search_similar_invoices": {"methods": [], "invoices": []}})
    client = start_app(llm, tools)

    invoice_id = upload_fraud(client)["id"]
    run = investigation(client, invoice_id)["run"]

    assert tools.calls == [("search_similar_invoices", invoice_id)]
    # The model wrote "current" and never saw the id.
    assert run["steps"][1]["argument"] == "current"
    assert all(invoice_id not in r.system + str(r.user) for r in llm.requests)


def test_the_agent_cannot_change_the_invoice(start_app: StartApp, engine: Engine) -> None:
    """Whatever the model asks for, the invoice, its audit log and its paused thread stay."""
    approve = json.dumps({"action": "approve_invoice", "invoice": "this one"})
    llm = FakeLLMClient(approve, call_tools(("set_status", "approved")))
    client = start_app(llm, FakeTools(), agent_auto_investigate=False)
    invoice_id = upload_fraud(client)["id"]
    before = audit_actions(engine, invoice_id)

    response = client.post(f"/invoices/{invoice_id}/investigate")
    assert response.status_code == 202, response.text
    run = investigation(client, invoice_id)["run"]

    assert (run["status"], run["stop_reason"]) == ("failed", "invalid_output")
    assert client.get(f"/invoices/{invoice_id}").json()["status"] == "blocked"
    assert audit_actions(engine, invoice_id) == before
    assert paused(engine, invoice_id)


def test_a_finished_investigation_leaves_the_decision_to_people(
    start_app: StartApp, engine: Engine
) -> None:
    client = start_app(FakeLLMClient(finish()), FakeTools())
    invoice_id = upload_fraud(client)["id"]
    assert investigation(client, invoice_id)["run"]["status"] == "completed"

    assert client.get(f"/invoices/{invoice_id}").json()["status"] == "blocked"
    assert paused(engine, invoice_id)
    assert not any(action.startswith("agent") for action in audit_actions(engine, invoice_id))


def test_an_injected_invoice_is_never_sent_to_the_model(start_app: StartApp) -> None:
    llm = FakeLLMClient()
    client = start_app(llm, FakeTools())
    sample = (SAMPLES / "06_it_service_injected_note.xml").read_bytes()
    invoice_id = upload(client, "injected.xml", sample)["id"]

    body = investigation(client, invoice_id)
    response = client.post(f"/invoices/{invoice_id}/investigate")

    assert body["run"] is None
    assert body["can_investigate"] is False
    assert body["reason"] == service.INJECTION_SUSPECTED
    assert response.status_code == 409
    assert response.json()["detail"] == service.INJECTION_SUSPECTED
    assert llm.requests == []


def test_only_blocked_invoices_are_investigated(start_app: StartApp) -> None:
    llm = FakeLLMClient()
    client = start_app(llm, FakeTools())
    invoice_id = upload(client, "clean.xml", (FIXTURES / "ubl_xrechnung.xml").read_bytes())["id"]

    response = client.post(f"/invoices/{invoice_id}/investigate")

    assert response.status_code == 409
    assert response.json()["detail"] == service.NOT_BLOCKED
    assert investigation(client, invoice_id)["run"] is None
    assert llm.requests == []


def test_investigate_starts_a_run_for_the_user(
    start_app: StartApp, engine: Engine, reviewer: Any
) -> None:
    client = start_app(FakeLLMClient(finish()), FakeTools(), agent_auto_investigate=False)
    invoice_id = upload_fraud(client)["id"]
    before = investigation(client, invoice_id)
    assert before["run"] is None and before["can_investigate"] and before["mode"] == "live"

    response = client.post(f"/invoices/{invoice_id}/investigate")

    assert response.status_code == 202
    assert investigation(client, invoice_id)["run"]["status"] == "completed"
    with Session(engine) as session:
        assert session.scalars(select(AgentRun.user_id)).one() == reviewer.id


def test_one_running_investigation_per_invoice(start_app: StartApp, engine: Engine) -> None:
    client = start_app(FakeLLMClient(), FakeTools(), agent_auto_investigate=False)
    invoice_id = upload_fraud(client)["id"]
    with Session(engine) as session:
        service.start_run(session, uuid.UUID(invoice_id), "gemini/test-model", None)

    response = client.post(f"/invoices/{invoice_id}/investigate")
    body = client.get(f"/invoices/{invoice_id}/investigation").json()

    assert response.status_code == 409
    assert response.json()["detail"] == "An investigation of this invoice is already running."
    assert body["can_investigate"] is False


def test_the_cost_cap_holds_across_runs(start_app: StartApp) -> None:
    llm = FakeLLMClient(*[call_tools(("get_supplier", "DE999000033"))] * 2)
    client = start_app(llm, FakeTools(), agent_cost_cap_usd=2 * COST_USD)
    stopped = sample_of(client)
    before = stopped("invoiceguard_agent_runs_total", status="stopped", reason="cost_cap")
    invoice_id = upload_fraud(client)["id"]
    first = investigation(client, invoice_id)["run"]

    client.post(f"/invoices/{invoice_id}/investigate")
    second = investigation(client, invoice_id)["run"]

    assert (first["status"], first["stop_reason"]) == ("stopped", "cost_cap")
    assert len(llm.requests) == 2
    assert (second["status"], second["stop_reason"], second["steps"]) == ("stopped", "cost_cap", [])
    assert second["id"] != first["id"]
    # The metric behind the "cost cap reached" alert (ADR-025).
    eventually(
        lambda: stopped("invoiceguard_agent_runs_total", status="stopped", reason="cost_cap"),
        before + 2,
    )


def test_the_daily_budget_stops_a_run_before_any_call(start_app: StartApp, engine: Engine) -> None:
    with Session(engine) as session:
        session.add(
            ModelCall(
                purpose="extraction",
                model="gemini/test-model",
                status=ModelCallStatus.OK,
                cost_usd=Decimal("0.02"),
                latency_ms=1,
            )
        )
        session.commit()
    llm = FakeLLMClient()
    client = start_app(llm, FakeTools(), llm_daily_budget_usd=Decimal("0.01"))

    run = investigation(client, upload_fraud(client)["id"])["run"]

    assert (run["status"], run["stop_reason"]) == ("stopped", "daily_budget")
    assert llm.requests == []


def test_an_internal_error_fails_the_run(start_app: StartApp) -> None:
    tools = FakeTools({"get_supplier": RuntimeError("bug")})
    client = start_app(FakeLLMClient(call_tools(("get_supplier", "DE999000033"))), tools)

    run = investigation(client, upload_fraud(client)["id"])["run"]

    assert (run["status"], run["stop_reason"]) == ("failed", "internal_error")
    assert run["error"] == service.INTERNAL_ERROR


def test_startup_fails_runs_a_restart_interrupted(
    start_app: StartApp, engine: Engine, settings: Settings, session_token: str
) -> None:
    client = start_app(FakeLLMClient(), FakeTools(), agent_auto_investigate=False)
    invoice_id = upload_fraud(client)["id"]
    with Session(engine) as session:
        service.start_run(session, uuid.UUID(invoice_id), "gemini/test-model", None)

    with TestClient(create_app(settings)) as restarted:
        restarted.cookies.set(SESSION_COOKIE, session_token)
        deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
        while (run := investigation(restarted, invoice_id)["run"])["status"] == "running":
            assert time.monotonic() < deadline
    assert (run["status"], run["stop_reason"]) == ("failed", "interrupted")


@pytest.fixture
def recordings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty folder of recorded runs in place of the packaged one."""
    monkeypatch.setattr(service, "RECORDED", tmp_path)
    return tmp_path


RECORDING: dict[str, Any] = {
    "scenario": {"seller_vat_id": "DE999000033", "failed_checks": ["iban"]},
    "recorded_at": "2026-11-18T10:00:00+00:00",
    "model": "gemini/gemini-3.8-flash",
    "finding": FINDING,
    "email_subject": "Rückfrage zu Ihrer Rechnung",
    "email_body": "Sehr geehrte Damen und Herren, ...",
    "input_tokens": 3000,
    "output_tokens": 500,
    "cost_usd": "0.004200",
    "duration_ms": 9000,
    "steps": [
        {"step_no": 1, "kind": "model", "tool": None, "argument": None, "result": None,
         "input_tokens": 3000, "output_tokens": 500, "cost_usd": "0.004200",
         "latency_ms": 8000, "error": None},
        {"step_no": 1, "kind": "tool", "tool": "check_iban", "argument": FRAUD_IBAN,
         "result": {"registered_to": []}, "input_tokens": None, "output_tokens": None,
         "cost_usd": None, "latency_ms": 40, "error": None},
    ],
}  # fmt: skip


def test_without_a_model_the_recorded_run_is_shown(
    start_app: StartApp, recordings: Path, engine: Engine, reviewer: Any
) -> None:
    (recordings / "iban.json").write_text(json.dumps(RECORDING), "utf-8")
    client = start_app()
    invoice_id = upload_fraud(client)["id"]
    before = investigation(client, invoice_id)
    assert before["run"] is None
    assert (before["mode"], before["can_investigate"]) == ("recorded", True)

    response = client.post(f"/invoices/{invoice_id}/investigate")

    assert response.status_code == 202
    run = response.json()["run"]
    assert (run["status"], run["source"]) == ("completed", "recorded")
    assert run["recorded_at"] == "2026-11-18T10:00:00Z"
    assert (run["finding"], run["cost_usd"], run["duration_ms"]) == (FINDING, "0.004200", 9000)
    assert run["email_to"] == IT_SERVICE_CONTACT
    assert [s["tool"] for s in run["steps"]] == [None, "check_iban"]
    with Session(engine) as session:
        # A recording costs nothing now: no model call is logged.
        assert session.scalar(select(func.count(ModelCall.id))) == 0
        assert session.get_one(Invoice, uuid.UUID(invoice_id)).status is InvoiceStatus.BLOCKED


def test_without_a_model_or_recording_investigating_is_unavailable(
    start_app: StartApp, recordings: Path
) -> None:
    (recordings / "other.json").write_text(
        json.dumps(
            {**RECORDING, "scenario": {"seller_vat_id": "DE999000025", "failed_checks": []}}
        ),
        "utf-8",
    )
    client = start_app()
    invoice_id = upload_fraud(client)["id"]

    body = investigation(client, invoice_id)
    response = client.post(f"/invoices/{invoice_id}/investigate")

    assert (body["mode"], body["can_investigate"]) == ("unavailable", False)
    assert body["reason"] == response.json()["detail"]
    assert response.status_code == 409


def test_the_agent_needs_all_three_mcp_servers(settings: Settings) -> None:
    from invoiceguard_api.main import make_agent

    urls = {
        "mcp_erp_url": "http://mcp-erp:8000/mcp",
        "mcp_registry_url": "http://r:8000/mcp",
        "mcp_history_url": "http://h:8000/mcp",
    }
    assert make_agent(settings, FakeLLMClient(), None) is None
    assert make_agent(settings, None, FakeTools()) is None
    without_history = settings.model_copy(update={**urls, "mcp_history_url": None})
    assert make_agent(without_history, FakeLLMClient(), None) is None
    agent = make_agent(settings.model_copy(update=urls), FakeLLMClient(), None)
    assert agent is not None
    assert agent.model == settings.extraction_model
    assert agent.embedding_model == settings.embedding_model
    assert agent.limits == replace(agent.limits, max_steps=8, max_tool_calls=12)


def _packaged() -> list[Traversable]:
    return [entry for entry in service.RECORDED.iterdir() if entry.name.endswith(".json")]


def test_packaged_recordings_match_a_demo_sample_case() -> None:
    """Each shipped recording is a complete run for a blocked demo sample (ADR-018)."""
    recordings = _packaged()
    assert recordings, "no recorded runs packaged for the demo"
    for entry in recordings:
        recording = json.loads(entry.read_text("utf-8"))
        assert recording["finding"] and recording["email_subject"] and recording["email_body"]
        assert recording["scenario"]["failed_checks"], entry.name
        assert recording["scenario"]["seller_vat_id"] in {s.vat_id for s in SUPPLIERS}
        assert {s["tool"] for s in recording["steps"] if s["tool"]} <= set(TOOLS)
        assert Decimal(recording["cost_usd"]) == sum(
            (Decimal(s["cost_usd"]) for s in recording["steps"] if s["cost_usd"]), Decimal(0)
        )


def test_the_case_file_bounds_check_evidence() -> None:
    from invoiceguard_api.models import Check, CheckStatus

    long_evidence = {"similar_invoices": [str(uuid.uuid4()) for _ in range(100)]}
    failed = Check(type="duplicate", status=CheckStatus.FAILED, message="x" * 1000,
                   evidence=long_evidence)  # fmt: skip
    warning = Check(type="supplier_known", status=CheckStatus.WARNING, message="Unknown.",
                    evidence={"seller_vat_id": "DE1"})  # fmt: skip
    small = Check(type="iban", status=CheckStatus.FAILED, message="IBAN.", evidence={"a": 1})

    assert service._check_entry(failed) == {
        "type": "duplicate",
        "status": "failed",
        "message": "x" * service.MAX_MESSAGE_CHARS,
        "evidence": "omitted: too long",
    }
    assert "evidence" not in service._check_entry(warning)
    assert service._check_entry(small)["evidence"] == {"a": 1}
