from decimal import Decimal

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


def test_llm_settings_default_to_extraction_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", DB_URL)
    # Docker Compose passes an unset variable as an empty string.
    monkeypatch.setenv("INVOICEGUARD_LLM_API_KEY", "")

    settings = Settings()

    assert settings.llm_api_key is None
    assert settings.extraction_model == "gemini/gemini-3.8-flash"
    assert settings.extraction_confidence_threshold == Decimal("0.8")
    assert settings.extraction_reasoning_effort == "low"


def test_llm_api_key_is_not_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", DB_URL)
    monkeypatch.setenv("INVOICEGUARD_LLM_API_KEY", "test-key-not-real")  # pragma: allowlist secret

    settings = Settings()

    assert settings.llm_api_key is not None
    assert "test-key-not-real" not in repr(settings)


@pytest.mark.parametrize("threshold", ["-0.1", "1.1"])
def test_confidence_threshold_is_between_0_and_1(
    monkeypatch: pytest.MonkeyPatch, threshold: str
) -> None:
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", DB_URL)
    monkeypatch.setenv("INVOICEGUARD_EXTRACTION_CONFIDENCE_THRESHOLD", threshold)

    with pytest.raises(ValidationError, match="extraction_confidence_threshold"):
        Settings()


def test_reasoning_effort_cannot_turn_thinking_off(monkeypatch: pytest.MonkeyPatch) -> None:
    # Gemini 3 has no "off"; LiteLLM would quietly send the lowest level instead.
    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", DB_URL)
    monkeypatch.setenv("INVOICEGUARD_EXTRACTION_REASONING_EFFORT", "none")

    with pytest.raises(ValidationError, match="extraction_reasoning_effort"):
        Settings()
