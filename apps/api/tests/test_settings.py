import pytest
from pydantic import ValidationError

from invoiceguard_api.settings import Settings

DB_URL = "postgresql+psycopg://user:pw@localhost:5432/invoiceguard"


def test_settings_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOICEGUARD_ENV", "prod")
    monkeypatch.setenv("INVOICEGUARD_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", DB_URL)
    monkeypatch.setenv("INVOICEGUARD_STORAGE_DIR", "/data/uploads")
    monkeypatch.setenv("INVOICEGUARD_MAX_UPLOAD_BYTES", "2048")

    settings = Settings()

    assert settings.env == "prod"
    assert settings.log_level == "WARNING"
    assert str(settings.database_url) == DB_URL
    assert settings.storage_dir.as_posix() == "/data/uploads"
    assert settings.max_upload_bytes == 2048


def test_invalid_log_level_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", DB_URL)
    monkeypatch.setenv("INVOICEGUARD_LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError, match="log_level"):
        Settings()


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INVOICEGUARD_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        Settings()


@pytest.mark.parametrize(
    "url", ["postgresql://user:pw@localhost/db", "mysql+pymysql://user:pw@localhost/db"]
)
def test_database_url_must_use_psycopg(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", url)

    with pytest.raises(ValidationError, match="database_url"):
        Settings()


def test_max_upload_bytes_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", DB_URL)
    monkeypatch.setenv("INVOICEGUARD_MAX_UPLOAD_BYTES", "0")

    with pytest.raises(ValidationError, match="max_upload_bytes"):
        Settings()
