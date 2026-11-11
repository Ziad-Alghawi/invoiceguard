import pytest
from pydantic import ValidationError

from invoiceguard_api.settings import Settings


def test_settings_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOICEGUARD_ENV", "prod")
    monkeypatch.setenv("INVOICEGUARD_LOG_LEVEL", "WARNING")

    settings = Settings()

    assert settings.env == "prod"
    assert settings.log_level == "WARNING"


def test_invalid_log_level_fails_fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOICEGUARD_LOG_LEVEL", "LOUD")

    with pytest.raises(ValidationError, match="log_level"):
        Settings()
