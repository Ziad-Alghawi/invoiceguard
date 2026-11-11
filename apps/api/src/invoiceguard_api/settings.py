"""Application settings, read from environment variables prefixed with INVOICEGUARD_."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["dev", "test", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INVOICEGUARD_", extra="ignore")

    env: Environment = "dev"
    log_level: LogLevel = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
