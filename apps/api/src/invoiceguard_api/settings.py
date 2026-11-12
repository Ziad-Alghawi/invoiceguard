"""Application settings, read from environment variables prefixed with INVOICEGUARD_."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, UrlConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

# Only the psycopg 3 driver is installed, so the URL must name it explicitly.
DatabaseUrl = Annotated[PostgresDsn, UrlConstraints(allowed_schemes=["postgresql+psycopg"])]

MIB = 1024 * 1024


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INVOICEGUARD_", extra="ignore")

    env: Environment = "dev"
    log_level: LogLevel = "INFO"
    database_url: DatabaseUrl
    storage_dir: Path = Path("data/uploads")
    max_upload_bytes: int = Field(default=10 * MIB, gt=0)
    # KoSIT validator service (ADR-009). Unset: the KoSIT check is skipped, nothing else changes.
    validator_url: AnyHttpUrl | None = None
    validator_timeout_seconds: float = Field(default=20.0, gt=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
