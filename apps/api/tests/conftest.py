"""Test fixtures. Database tests run against a real PostgreSQL (the Compose db locally, a service
container in CI), in a separate database that is created and migrated once per test session."""

import io
import os
from collections.abc import Callable, Iterator
from pathlib import Path

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
from invoiceguard_api.settings import Settings

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
def settings(database_url: str, tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        log_level="DEBUG",
        database_url=PostgresDsn(database_url),
        storage_dir=tmp_path / "uploads",
        max_upload_bytes=TEST_MAX_UPLOAD_BYTES,
    )


@pytest.fixture
def client(settings: Settings, engine: Engine) -> Iterator[TestClient]:
    """App client on the test database; requesting `engine` empties the tables afterwards."""
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _pdf(attachment: tuple[str, bytes] | None = None) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(*A4_POINTS)
    if attachment is not None:
        writer.add_attachment(*attachment)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


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
    }


@pytest.fixture
def pdf_with_attachment() -> Callable[[str, bytes], bytes]:
    """Builds a blank PDF with one attached file, for hostile or unusual attachments."""
    return lambda filename, content: _pdf((filename, content))
