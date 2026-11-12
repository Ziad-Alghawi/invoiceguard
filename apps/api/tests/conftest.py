"""Test fixtures. Database tests run against a real PostgreSQL (the Compose db locally, a service
container in CI), in a separate database that is created and migrated once per test session."""

import io
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from facturx import generate_from_binary
from fastapi.testclient import TestClient
from pydantic import PostgresDsn
from pypdf import PdfWriter
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.main import create_app
from invoiceguard_api.models import Base
from invoiceguard_api.seed import seed_demo_data
from invoiceguard_api.settings import Settings

# Whatever imports LiteLLM first, it must use its bundled price table and never download one
# (ADR-004), and must not load the developer's .env (with a real API key) into the environment;
# the app sets both in llm/litellm_client.py, which test_litellm_client.py checks.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

TEST_DATABASE_URL_ENV = "INVOICEGUARD_TEST_DATABASE_URL"
API_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
# Larger than every sample invoice, far below the 200 kB request in the body-limit test.
TEST_MAX_UPLOAD_BYTES = 32 * 1024
A4_POINTS = (595, 842)


def alembic_config(database_url: str) -> Config:
    config = Config(API_DIR / "alembic.ini")
    # configparser treats % as interpolation, e.g. in a URL-encoded password.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    raw_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not raw_url:
        pytest.fail(f"Set {TEST_DATABASE_URL_ENV} (see .env.example) or run `make test`.")
    url = make_url(raw_url)
    # The database is dropped and recreated, so never point the tests at a real one.
    if not (url.database or "").endswith("_test"):
        pytest.fail(f"{TEST_DATABASE_URL_ENV} must name a database ending in _test.")

    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    test_url = url.render_as_string(hide_password=False)
    command.upgrade(alembic_config(test_url), "head")
    yield test_url
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def alembic_cfg(database_url: str) -> Config:
    return alembic_config(database_url)


@pytest.fixture(scope="session")
def session_engine(database_url: str) -> Iterator[Engine]:
    engine = make_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def engine(session_engine: Engine) -> Iterator[Engine]:
    """The test database engine; every table is emptied after the test."""
    yield session_engine
    tables = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with session_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    with make_session_factory(engine)() as session:
        yield session


@pytest.fixture
def seeded(db_session: Session) -> None:
    """The German demo suppliers, verified IBANs and purchase orders (`make seed`)."""
    seed_demo_data(db_session)
    db_session.commit()


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        log_level="DEBUG",
        database_url=PostgresDsn(database_url),
        storage_dir=tmp_path / "uploads",
        max_upload_bytes=TEST_MAX_UPLOAD_BYTES,
        # Never a real key from the environment: tests use the fake client (tests/fakes.py).
        llm_api_key=None,
    )


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    """App client on the test database; requesting `engine` empties the tables afterwards."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


# Processing a sample takes milliseconds; this is only a ceiling for a stuck test.
PROCESSING_TIMEOUT_SECONDS = 10.0
FinishedInvoice = Callable[[str], dict[str, Any]]


def poll_until_done(
    client: TestClient, url: str, waiting: frozenset[str] = frozenset({"received", "processing"})
) -> dict[str, Any]:
    """GET an invoice URL until its status is not in `waiting`, as the UI polls it (ADR-007)."""
    deadline = time.monotonic() + PROCESSING_TIMEOUT_SECONDS
    while True:
        detail: dict[str, Any] = client.get(url).json()
        if detail["status"] not in waiting:
            return detail
        assert time.monotonic() < deadline, f"still {detail['status']}: {url}"
        time.sleep(0.02)


@pytest.fixture
def finished(client: TestClient) -> FinishedInvoice:
    """GET an invoice URL until processing has finished, as the UI polls it (ADR-007).

    Usually the upload's background task has finished before the response returns. But startup
    recovery runs on another thread and may claim a fresh upload first; the background task then
    skips it, and the invoice is still `processing` when the response arrives.
    """

    def get(url: str) -> dict[str, Any]:
        return poll_until_done(client, url)

    return get


def _pdf(attachment: tuple[str, bytes] | None = None) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(*A4_POINTS)
    if attachment is not None:
        writer.add_attachment(*attachment)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _pdf_string(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return b"(" + escaped.encode("latin-1") + b")"


def text_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a real text layer (Helvetica), written by hand: pypdf has no text API.

    Like an invoice printed to PDF by an office program, without e-invoice XML.
    """
    shown = b" ".join(_pdf_string(line) + b" '" for line in lines)
    content = b"BT /F1 11 Tf 50 790 Td 15 TL " + shown + b" ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] " % A4_POINTS
        + b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
    ]
    pdf = b"%PDF-1.7\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    pdf += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return pdf


# The printed text of ubl_xrechnung.xml, as a plain PDF invoice would show it.
INVOICE_TEXT = [
    "Demo IT-Service GmbH, Musterstrasse 1, 10115 Berlin, USt-IdNr.: DE999000033",
    "An: Beispielkunde Handels GmbH, USt-IdNr.: DE999000068",
    "Rechnung Nr. 2026-IT-0815 vom 05.11.2026, Ihre Bestellung: PO-2026-0005",
    "1  Notebook 14 Zoll, 32 GB RAM      3 Stk   1.249,00   3.747,00",
    "2  Einrichtung und Inbetriebnahme   6 Std      95,00     570,00",
    "Nettobetrag 4.317,00 EUR   zzgl. 19 % USt 820,23 EUR   Gesamtbetrag 5.137,23 EUR",
    "Zahlbar bis 19.11.2026 auf IBAN DE60 1234 5678 0000 0000 03",
]


@pytest.fixture(scope="session")
def samples() -> dict[str, bytes]:
    """The sample invoices by kind. All data is made up; PDFs are built here, not committed."""
    xml = {path.stem: path.read_bytes() for path in FIXTURES.glob("*.xml")}
    return {
        **xml,
        # factur-x attaches the XML and writes the Factur-X metadata, as invoicing software does.
        "zugferd2_pdf": generate_from_binary(_pdf(), xml["zugferd2_basic"], check_xsd=False),
        # ZUGFeRD 1.0 used the attachment name ZUGFeRD-invoice.xml.
        "zugferd1_pdf": _pdf(("ZUGFeRD-invoice.xml", xml["zugferd1"])),
        "plain_pdf": _pdf(),
        "text_pdf": text_pdf(INVOICE_TEXT),
    }


@pytest.fixture
def pdf_with_attachment() -> Callable[[str, bytes], bytes]:
    """Builds a blank PDF with one attached file, for hostile or unusual attachments."""
    return lambda filename, content: _pdf((filename, content))
