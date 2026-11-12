from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from invoiceguard_api.models import Base

TABLES = {
    "invoices",
    "invoice_fields",
    "suppliers",
    "supplier_bank_accounts",
    "purchase_orders",
    "purchase_order_lines",
    "checks",
    "audit_events",
    "model_calls",
}


@pytest.fixture
def migrated(engine: Engine, alembic_cfg: Config) -> Iterator[Config]:
    """Alembic config for the test database; the schema is back at head after the test."""
    yield alembic_cfg
    command.upgrade(alembic_cfg, "head")


def table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names()) - {"alembic_version"}


def test_head_creates_exactly_the_model_tables(engine: Engine) -> None:
    assert table_names(engine) == TABLES
    assert set(Base.metadata.tables) == TABLES


def test_downgrade_to_base_and_upgrade_again(engine: Engine, migrated: Config) -> None:
    command.downgrade(migrated, "base")
    assert table_names(engine) == set()

    command.upgrade(migrated, "head")
    assert table_names(engine) == TABLES


def test_models_match_the_migrations(alembic_cfg: Config) -> None:
    # Fails when a model changes without a migration (same as `alembic check`).
    command.check(alembic_cfg)
