"""Test fixtures. The decision tests run the app against a real PostgreSQL, like the api tests: a
database named after INVOICEGUARD_TEST_DATABASE_URL with `_eval` appended, dropped and recreated."""

import os

import pytest
from sqlalchemy.engine import make_url

# As in the api tests: LiteLLM must use its bundled price table and never load a developer .env.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_MODE", "PRODUCTION")

TEST_DATABASE_URL_ENV = "INVOICEGUARD_TEST_DATABASE_URL"


@pytest.fixture(scope="session")
def eval_database_url() -> str:
    raw_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if not raw_url:
        pytest.fail(f"Set {TEST_DATABASE_URL_ENV} (see .env.example) or run `make test`.")
    url = make_url(raw_url)
    if not (url.database or "").endswith("_test"):
        pytest.fail(f"{TEST_DATABASE_URL_ENV} must name a database ending in _test.")
    return url.set(database=f"{url.database}_eval").render_as_string(hide_password=False)
