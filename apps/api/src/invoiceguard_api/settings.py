"""Application settings, read from environment variables prefixed with INVOICEGUARD_."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr, UrlConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

from invoiceguard_api.llm import ReasoningEffort

Environment = Literal["dev", "test", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

# Only the psycopg 3 driver is installed, so the URL must name it explicitly.
DatabaseUrl = Annotated[PostgresDsn, UrlConstraints(allowed_schemes=["postgresql+psycopg"])]

MIB = 1024 * 1024


class Settings(BaseSettings):
    # An empty variable counts as unset, so Compose can pass `${VAR:-}` for optional settings.
    model_config = SettingsConfigDict(
        env_prefix="INVOICEGUARD_", extra="ignore", env_ignore_empty=True
    )

    env: Environment = "dev"
    log_level: LogLevel = "INFO"
    database_url: DatabaseUrl
    storage_dir: Path = Path("data/uploads")
    max_upload_bytes: int = Field(default=10 * MIB, gt=0)
    # KoSIT validator service (ADR-009). Unset: the KoSIT check is skipped, nothing else changes.
    validator_url: AnyHttpUrl | None = None
    validator_timeout_seconds: float = Field(default=20.0, gt=0)
    # LLM extraction of plain PDFs (ADR-004, ADR-010). No key: PDFs stay `awaiting_extraction`.
    llm_api_key: SecretStr | None = None
    # A LiteLLM model string; its price must be in LiteLLM's price table (ADR-004).
    extraction_model: str = "gemini/gemini-3.8-flash"
    # Thinking tokens are billed as output; `low` is the lowest level Gemini 3.8 Flash accepts in
    # the pinned LiteLLM version (`minimal` is sent as `low`), see ADR-010.
    extraction_reasoning_effort: ReasoningEffort = "low"
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    # Fields extracted with a lower confidence get a `low_confidence` check result.
    extraction_confidence_threshold: Decimal = Field(default=Decimal("0.8"), ge=0, le=1)
    # Login sessions (ADR-011): fixed lifetime, then log in again.
    session_ttl_minutes: int = Field(default=8 * 60, gt=0)
    # This many failed logins in a row lock the account for `login_lockout_minutes`.
    login_max_failures: int = Field(default=5, gt=0)
    login_lockout_minutes: int = Field(default=15, gt=0)

    @property
    def secure_cookies(self) -> bool:
        """Session cookies only over HTTPS in prod; dev and test run on plain http://localhost."""
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
