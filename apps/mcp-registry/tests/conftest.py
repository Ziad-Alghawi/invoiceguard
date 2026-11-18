"""Test fixtures: a database of its own, built by the api's migrations and demo seed (apps/api
owns the schema), and the server connected in-process as the `invoiceguard_mcp_registry` role.

The tests log in with the test database's admin user and switch to the role at connection start
(`-c role=...`), so PostgreSQL applies exactly the role's grants without the tests ever setting
the role's password (roles are shared by every database on the server).
"""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from invoiceguard_mcp_registry.db import Database

TEST_DATABASE_URL_ENV = "INVOICEGUARD_TEST_DATABASE_URL"
API_DIR = Path(__file__).resolve().parents[2] / "api"
ROLE = "invoiceguard_mcp_registry"


def _libpq_url(url: str) -> str:
    """The api's SQLAlchemy URL (postgresql+psycopg://...) as a plain libpq URL."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="session")
def admin_url() -> Iterator[str]:
    raw = os.environ.get(TEST_DATABASE_URL_ENV)
    if not raw:
        pytest.fail(f"Set {TEST_DATABASE_URL_ENV} (see .env.example) or run `make test`.")
    base = psycopg.conninfo.conninfo_to_dict(_libpq_url(raw))
    if not str(base.get("dbname", "")).endswith("_test"):
        pytest.fail(f"{TEST_DATABASE_URL_ENV} must name a database ending in _test.")
    name = f"{str(base['dbname']).removesuffix('_test')}_mcp_registry_test"
    with psycopg.connect(make_conninfo(_libpq_url(raw), dbname="postgres"), autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{name}"')
    url = raw.rsplit("/", 1)[0] + f"/{name}"
    env = {**os.environ, "INVOICEGUARD_DATABASE_URL": url}
    for command in (["alembic", "upgrade", "head"], ["invoiceguard-seed"]):
        subprocess.run(["uv", "run", "--frozen", *command], cwd=API_DIR, env=env, check=True)
    yield _libpq_url(url)
    with psycopg.connect(make_conninfo(_libpq_url(raw), dbname="postgres"), autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def database(admin_url: str) -> Database:
    return Database(make_conninfo(admin_url, options=f"-c role={ROLE}"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
