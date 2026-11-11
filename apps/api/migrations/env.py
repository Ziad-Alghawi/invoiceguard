"""Alembic environment: runs migrations online against INVOICEGUARD_DATABASE_URL."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from invoiceguard_api.models import Base
from invoiceguard_api.settings import get_settings

config = context.config

# Tests run migrations in-process and keep their own logging setup.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url") or str(get_settings().database_url)
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported; run against a database.")
run_migrations_online()
