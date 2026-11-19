"""The fraud set through the whole app (ADR-019): `create_app` with the real graph, checks and
database, each case uploaded with `POST /invoices` like a user would, the status and check
results read back from `GET /invoices/{id}`.

Every variant (XML, PDF) gets a fresh database, migrated and seeded with the demo master data,
because the duplicate check compares with every stored invoice.
"""

import secrets
import tempfile
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import invoiceguard_api
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from invoiceguard_api.auth import SESSION_COOKIE, hash_password, token_hash
from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.llm import LLMClient, ReasoningEffort
from invoiceguard_api.main import create_app
from invoiceguard_api.models import User, UserRole, UserSession
from invoiceguard_api.seed import seed_demo_data
from invoiceguard_api.settings import Settings
from pydantic import AnyHttpUrl, PostgresDsn
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from invoiceguard_evals.datasets import GENERATED_DIR
from invoiceguard_evals.metrics import Decision
from invoiceguard_evals.specs import InvoiceSpec

Variant = Literal["xml", "pdf"]
ALEMBIC_INI = Path(invoiceguard_api.__file__).resolve().parents[2] / "alembic.ini"
# Statuses a client waits through (ADR-007); with a model, `awaiting_extraction` is one of them.
WAITING = frozenset({"received", "processing", "awaiting_extraction"})
TIMEOUT_SECONDS = 300
FLAGGED = frozenset({"failed", "warning"})
KOSIT = "kosit"


class EvalDatabaseError(Exception):
    """The eval database URL is missing or could name a real database."""


def recreate_database(url: str) -> str:
    """Drop and create the eval database and migrate it to head; returns its URL."""
    parsed = make_url(url)
    # The database is dropped, so never anything but a database for the eval.
    if not (parsed.database or "").endswith("_eval"):
        raise EvalDatabaseError(
            "INVOICEGUARD_EVAL_DATABASE_URL must name a database ending in _eval."
        )
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{parsed.database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    admin.dispose()
    rendered = parsed.render_as_string(hide_password=False)
    config = Config(ALEMBIC_INI)
    config.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    command.upgrade(config, "head")
    return rendered


def _login(url: str) -> str:
    """Seed the demo master data and one reviewer; returns a session token for that user."""
    engine = make_engine(url)
    token = secrets.token_urlsafe(32)
    with make_session_factory(engine)() as session:
        seed_demo_data(session)
        user = User(
            email="eval@invoiceguard.example",
            display_name="Eval",
            # Never used to log in: the session row below is the login.
            password_hash=hash_password(secrets.token_urlsafe(24)),
            role=UserRole.REVIEWER,
            failed_logins=0,
        )
        session.add(user)
        session.flush()
        session.add(
            UserSession(
                token_hash=token_hash(token),
                user_id=user.id,
                expires_at=datetime.now(UTC) + timedelta(hours=2),
            )
        )
        session.commit()
    engine.dispose()
    return token


@contextmanager
def app_client(
    database_url: str,
    llm_client: LLMClient | None,
    reasoning_effort: ReasoningEffort,
    validator_url: str | None,
    threshold: Decimal,
) -> Iterator[TestClient]:
    url = recreate_database(database_url)
    token = _login(url)
    with tempfile.TemporaryDirectory() as storage:
        settings = Settings(
            env="dev",
            database_url=PostgresDsn(url),
            storage_dir=Path(storage),
            validator_url=None if validator_url is None else AnyHttpUrl(validator_url),
            # The recording client stands in for the model; no key, no agent (no MCP URLs).
            llm_api_key=None,
            extraction_reasoning_effort=reasoning_effort,
            extraction_confidence_threshold=threshold,
            llm_daily_budget_usd=None,
            mcp_erp_url=None,
            mcp_registry_url=None,
            upload_max_per_hour=None,
            demo_mode=False,
        )
        with TestClient(create_app(settings, llm_client=llm_client)) as client:
            client.cookies.set(SESSION_COOKIE, token)
            yield client


def process(client: TestClient, name: str, content: bytes) -> dict[str, Any]:
    response = client.post("/invoices", files={"file": (name, content, "application/octet-stream")})
    response.raise_for_status()
    location = response.headers["location"]
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while True:
        detail: dict[str, Any] = client.get(location).json()
        if detail["status"] not in WAITING:
            return detail
        if time.monotonic() > deadline:
            raise TimeoutError(f"{name} is still {detail['status']}")
        time.sleep(0.05)


def evaluate_decisions(
    client: TestClient,
    specs: Sequence[InvoiceSpec],
    variant: Variant,
    validator: bool,
    directory: Path = GENERATED_DIR,
) -> list[Decision]:
    """Upload the cases in order (a duplicate after its original) and read the decisions.

    Without a validator the KoSIT check is skipped, so it is not expected to flag anything."""
    suffix = ".ubl.xml" if variant == "xml" else ".pdf"
    decisions = []
    for spec in specs:
        if spec.expected is None:
            continue
        detail = process(
            client, spec.case_id + suffix, (directory / (spec.case_id + suffix)).read_bytes()
        )
        expected = spec.expected.flags
        if variant == "xml":
            expected |= spec.expected.xml_only_flags
        if not validator:
            expected -= {KOSIT}
        decisions.append(
            Decision(
                case_id=spec.case_id,
                variant=variant,
                status=detail["status"],
                flags=frozenset(c["type"] for c in detail["checks"] if c["status"] in FLAGGED),
                expected_status=spec.expected.status,
                expected_flags=expected,
                fraud_type=spec.expected.fraud_type,
                primary_check=spec.expected.primary_check,
            )
        )
    return decisions
