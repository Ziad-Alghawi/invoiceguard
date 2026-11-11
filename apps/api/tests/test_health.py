from fastapi.testclient import TestClient
from pydantic import PostgresDsn

from invoiceguard_api.main import create_app
from invoiceguard_api.settings import Settings


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_database_answers(client: TestClient) -> None:
    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_not_ready_when_database_is_unreachable() -> None:
    # Port 1 on localhost refuses connections immediately.
    settings = Settings(
        env="test", database_url=PostgresDsn("postgresql+psycopg://user:pw@127.0.0.1:1/x_test")
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
