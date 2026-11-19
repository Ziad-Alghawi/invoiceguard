"""Give the restricted database roles their login passwords: the api's `invoiceguard_app`
(migration 0014, ADR-022) and the MCP servers' roles (migrations 0010 and 0013, ADR-017).

The migrations create the roles without LOGIN and grant their rights; the passwords are
secrets, so they come from the environment here, never from a migration. A role with a password
can log in; a role whose password variable is empty or unset cannot (NOLOGIN), so removing a
password from the .env locks the role out at the next start.

Runs as the database owner after `alembic upgrade head` in the one-shot `migrate` step, never
in the api (whose role may not change roles); safe to run again. Run by hand with
`uv run invoiceguard-db-roles`.
"""

import logging
from collections.abc import Mapping

from psycopg import sql
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine

from invoiceguard_api.db import make_engine
from invoiceguard_api.logging import configure_logging
from invoiceguard_api.settings import get_settings

logger = logging.getLogger(__name__)

APP_ROLE = "invoiceguard_app"
ERP_ROLE = "invoiceguard_mcp_erp"
REGISTRY_ROLE = "invoiceguard_mcp_registry"
HISTORY_ROLE = "invoiceguard_mcp_history"


class RolePasswords(BaseSettings):
    """Read here only, so the passwords are not part of the app's settings."""

    model_config = SettingsConfigDict(
        env_prefix="INVOICEGUARD_", extra="ignore", env_ignore_empty=True
    )

    app_db_password: SecretStr | None = None
    mcp_erp_db_password: SecretStr | None = None
    mcp_registry_db_password: SecretStr | None = None
    mcp_history_db_password: SecretStr | None = None

    def by_role(self) -> dict[str, SecretStr | None]:
        return {
            APP_ROLE: self.app_db_password,
            ERP_ROLE: self.mcp_erp_db_password,
            REGISTRY_ROLE: self.mcp_registry_db_password,
            HISTORY_ROLE: self.mcp_history_db_password,
        }


def statement(role: str, password: SecretStr | None) -> sql.Composed:
    if password is None:
        return sql.SQL("ALTER ROLE {} WITH NOLOGIN PASSWORD NULL").format(sql.Identifier(role))
    return sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
        sql.Identifier(role), sql.Literal(password.get_secret_value())
    )


def apply_passwords(engine: Engine, passwords: Mapping[str, SecretStr | None]) -> list[str]:
    """Set or clear each role's password; returns the roles that can log in."""
    can_login = []
    with engine.begin() as connection:
        cursor = connection.connection.driver_connection.cursor()  # type: ignore[union-attr]
        for role, password in passwords.items():
            cursor.execute(statement(role, password))
            if password is not None:
                can_login.append(role)
    return can_login


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = make_engine(str(settings.database_url))
    try:
        can_login = apply_passwords(engine, RolePasswords().by_role())
    finally:
        engine.dispose()
    logger.info("Database roles that can log in: %s", ", ".join(can_login) or "none")
