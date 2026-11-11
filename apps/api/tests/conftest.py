"""Test fixtures. Database tests run against a real PostgreSQL (the Compose db locally, a service
container in CI), in a separate database that is created and migrated once per test session."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import PostgresDsn
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.main import create_app
from invoiceguard_api.models import Base
from invoiceguard_api.settings import Settings

TEST_DATABASE_URL_ENV = "INVOICEGUARD_TEST_DATABASE_URL"
API_DIR = Path(__file__).resolve().parents[1]
TEST_MAX_UPLOAD_BYTES = 4096


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
