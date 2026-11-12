"""Application settings, read from environment variables prefixed with INVOICEGUARD_."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr, UrlConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    # Fields extracted with a lower confidence get a `low_confidence` check result.
    extraction_confidence_threshold: Decimal = Field(default=Decimal("0.8"), ge=0, le=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
