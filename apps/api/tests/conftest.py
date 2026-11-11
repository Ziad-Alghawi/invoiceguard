from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from invoiceguard_api.main import create_app
from invoiceguard_api.settings import Settings


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(env="test", log_level="DEBUG"))
    with TestClient(app) as test_client:
        yield test_client
