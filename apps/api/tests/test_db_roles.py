"""The restricted database roles. The MCP servers' (migrations 0010 and 0013, ADR-017) each read
only their own tables, views and columns and write nothing; the api's (migration 0014, ADR-022)
reads and writes data but cannot TRUNCATE, change the schema or the append-only logs.

The checks run as the role with `SET LOCAL ROLE` inside a rolled-back transaction, so PostgreSQL
applies exactly that role's privileges. The tests never change the roles' passwords: roles
belong to the whole server, and the dev stack's MCP servers use the same ones.
"""

import secrets
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import errors
from pydantic import SecretStr
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import ProgrammingError

from invoiceguard_api import db_roles
from invoiceguard_api.checkpoints import open_checkpointer
from invoiceguard_api.db import make_engine
from invoiceguard_api.db_roles import (
    APP_ROLE,
    ERP_ROLE,
    HISTORY_ROLE,
    REGISTRY_ROLE,
    RolePasswords,
    apply_passwords,
)
from invoiceguard_api.settings import Settings, get_settings

ERP_TABLES = (
    "suppliers",
    "purchase_orders",
    "purchase_order_lines",
    "goods_receipts",
    "goods_receipt_lines",
)
REGISTRY_TABLES = ("supplier_bank_accounts",)
REGISTRY_SUPPLIER_COLUMNS = ("id", "name", "vat_id", "country_code")
APP_TABLES = (
    "invoices",
    "invoice_fields",
    "checks",
    "users",
    "sessions",
    "audit_events",
    "security_events",
    "model_calls",
    "datev_exports",
)
HISTORY_VIEWS = ("history_lines", "history_invoices", "invoice_item_names")
ROLES = (ERP_ROLE, REGISTRY_ROLE, HISTORY_ROLE)


@pytest.fixture
def connection(engine: Engine, seeded: None) -> Iterator[Connection]:
    with engine.connect() as connection:
        yield connection


def run_as(connection: Connection, role: str, statement: str) -> None:
    """Run one statement as the role; everything is rolled back afterwards."""
    transaction = connection.begin()
    try:
        connection.execute(text(f"SET LOCAL ROLE {role}"))
        connection.execute(text(statement))
    finally:
        transaction.rollback()


def assert_refused(connection: Connection, role: str, statement: str) -> None:
    with pytest.raises(ProgrammingError) as caught:
        run_as(connection, role, statement)
    assert isinstance(caught.value.orig, errors.InsufficientPrivilege), statement


@pytest.mark.parametrize("table", ERP_TABLES)
def test_erp_role_reads_its_tables(connection: Connection, table: str) -> None:
    run_as(connection, ERP_ROLE, f"SELECT * FROM {table}")


@pytest.mark.parametrize("table", (*REGISTRY_TABLES, *APP_TABLES, *HISTORY_VIEWS, "bookings"))
def test_erp_role_cannot_read_other_tables(connection: Connection, table: str) -> None:
    assert_refused(connection, ERP_ROLE, f"SELECT * FROM {table}")


def test_registry_role_reads_its_tables_and_columns(connection: Connection) -> None:
    run_as(connection, REGISTRY_ROLE, "SELECT * FROM supplier_bank_accounts")
    run_as(
        connection, REGISTRY_ROLE, f"SELECT {', '.join(REGISTRY_SUPPLIER_COLUMNS)} FROM suppliers"
    )


@pytest.mark.parametrize("column", ["street", "city", "contact_email", "*"])
def test_registry_role_cannot_read_other_supplier_columns(
    connection: Connection, column: str
) -> None:
    assert_refused(connection, REGISTRY_ROLE, f"SELECT {column} FROM suppliers")


@pytest.mark.parametrize(
    "table",
    ("purchase_orders", "purchase_order_lines", "goods_receipts", *APP_TABLES, *HISTORY_VIEWS),
)
def test_registry_role_cannot_read_other_tables(connection: Connection, table: str) -> None:
    assert_refused(connection, REGISTRY_ROLE, f"SELECT * FROM {table}")


@pytest.mark.parametrize(
    "statement",
    [
        *(f"SELECT * FROM {view}" for view in HISTORY_VIEWS),
        "SELECT * FROM rulebook_chunks",
        "SELECT model, text_sha256, vector FROM embeddings",
    ],
)
def test_history_role_reads_its_views(connection: Connection, statement: str) -> None:
    run_as(connection, HISTORY_ROLE, statement)


@pytest.mark.parametrize(
    "statement",
    [
        *(f"SELECT * FROM {table}" for table in (*APP_TABLES, *ERP_TABLES, *REGISTRY_TABLES)),
        "SELECT * FROM bookings",
        "SELECT * FROM agent_runs",
        # The embeddings' texts are every invoice's line texts; the role reads only vectors.
        "SELECT text FROM embeddings",
        "SELECT * FROM embeddings",
    ],
)
def test_history_role_cannot_read_anything_else(connection: Connection, statement: str) -> None:
    assert_refused(connection, HISTORY_ROLE, statement)


WRITES = (
    (ERP_ROLE, "INSERT INTO purchase_orders (id, number, supplier_id, order_date, currency) "
     "SELECT gen_random_uuid(), 'PO-X', id, current_date, 'EUR' FROM suppliers LIMIT 1"),
    (ERP_ROLE, "UPDATE suppliers SET name = 'x'"),
    (ERP_ROLE, "UPDATE purchase_order_lines SET unit_price = 0"),
    (ERP_ROLE, "DELETE FROM goods_receipts"),
    (ERP_ROLE, "TRUNCATE goods_receipt_lines"),
    (ERP_ROLE, "UPDATE invoices SET status = 'approved'"),
    (REGISTRY_ROLE, "INSERT INTO supplier_bank_accounts (id, supplier_id, iban, verified, since) "
     "SELECT gen_random_uuid(), id, 'DE00', true, current_date FROM suppliers LIMIT 1"),
    (REGISTRY_ROLE, "UPDATE supplier_bank_accounts SET verified = true"),
    (REGISTRY_ROLE, "DELETE FROM supplier_bank_accounts"),
    (REGISTRY_ROLE, "TRUNCATE supplier_bank_accounts"),
    (REGISTRY_ROLE, "UPDATE suppliers SET name = 'x'"),
    (HISTORY_ROLE, "UPDATE rulebook_chunks SET text = 'x'"),
    (HISTORY_ROLE, "DELETE FROM rulebook_chunks"),
    (HISTORY_ROLE, "TRUNCATE rulebook_chunks"),
    (HISTORY_ROLE, "UPDATE embeddings SET vector = vector"),
    (HISTORY_ROLE, "UPDATE invoice_item_names SET item_name = 'x'"),
    (ERP_ROLE, "CREATE TABLE public.mcp_scratch (id int)"),
    (REGISTRY_ROLE, "CREATE TABLE public.mcp_scratch (id int)"),
    (HISTORY_ROLE, "CREATE TABLE public.mcp_scratch (id int)"),
)  # fmt: skip


@pytest.mark.parametrize(("role", "statement"), WRITES)
def test_roles_cannot_write(connection: Connection, role: str, statement: str) -> None:
    assert_refused(connection, role, statement)


def test_roles_cannot_read_the_graph_checkpoints(connection: Connection) -> None:
    for role in ROLES:
        assert_refused(connection, role, "SELECT * FROM langgraph.checkpoints")


def test_roles_have_no_login_without_a_password(engine: Engine) -> None:
    # Fresh from the migration (or after `invoiceguard-db-roles` without passwords) a role
    # cannot log in. Only the attributes are read here; see the module docstring.
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT rolname, rolsuper, rolcreaterole, rolcreatedb FROM pg_roles "
                 "WHERE rolname IN (:erp, :registry, :history)"),
            {"erp": ERP_ROLE, "registry": REGISTRY_ROLE, "history": HISTORY_ROLE},
        ).all()  # fmt: skip
    assert {row.rolname for row in rows} == set(ROLES)
    assert not any(row.rolsuper or row.rolcreaterole or row.rolcreatedb for row in rows)


@pytest.fixture
def scratch_role(engine: Engine) -> Iterator[str]:
    """A role of its own, so setting passwords cannot affect the real MCP roles."""
    role = f"invoiceguard_test_{secrets.token_hex(4)}"
    with engine.begin() as connection:
        connection.execute(text(f"CREATE ROLE {role} NOLOGIN"))
    yield role
    with engine.begin() as connection:
        connection.execute(text(f"DROP ROLE {role}"))


def can_login(engine: Engine, role: str) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT rolcanlogin FROM pg_roles WHERE rolname = :role"), {"role": role}
            ).scalar_one()
        )


def test_apply_passwords_sets_and_clears_login(engine: Engine, scratch_role: str) -> None:
    password = SecretStr(secrets.token_urlsafe(16))

    assert apply_passwords(engine, {scratch_role: password}) == [scratch_role]
    assert can_login(engine, scratch_role)

    assert apply_passwords(engine, {scratch_role: None}) == []
    assert not can_login(engine, scratch_role)


def test_statement_quotes_the_password() -> None:
    rendered = db_roles.statement("r", SecretStr("it's")).as_string()
    assert rendered == "ALTER ROLE \"r\" WITH LOGIN PASSWORD 'it''s'"


def test_role_passwords_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVOICEGUARD_MCP_ERP_DB_PASSWORD", "erp-secret")
    monkeypatch.setenv("INVOICEGUARD_MCP_REGISTRY_DB_PASSWORD", "")
    monkeypatch.setenv("INVOICEGUARD_MCP_HISTORY_DB_PASSWORD", "history-secret")

    passwords = RolePasswords().by_role()

    assert passwords[ERP_ROLE] == SecretStr("erp-secret")
    assert passwords[REGISTRY_ROLE] is None
    assert passwords[HISTORY_ROLE] == SecretStr("history-secret")


def test_main_applies_the_passwords(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    applied: list[dict[str, SecretStr | None]] = []

    def record(_: Engine, passwords: dict[str, SecretStr | None]) -> list[str]:
        applied.append(dict(passwords))
        return []

    monkeypatch.setenv("INVOICEGUARD_DATABASE_URL", database_url)
    monkeypatch.setenv("INVOICEGUARD_MCP_ERP_DB_PASSWORD", "erp-secret")
    monkeypatch.setattr(db_roles, "apply_passwords", record)
    get_settings.cache_clear()
    try:
        db_roles.main()
    finally:
        get_settings.cache_clear()

    assert applied[0][ERP_ROLE] == SecretStr("erp-secret")
    assert applied[0][APP_ROLE] is None


# --- The api's role (migration 0014, ADR-022) --------------------------------------------------


def test_the_api_runs_as_the_app_role(settings: Settings) -> None:
    """The tests' app connects like the deployed api: as the restricted role, also for the
    graph's checkpointer, which opens connections of its own."""
    engine = make_engine(str(settings.database_url))
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT current_user")).scalar_one() == APP_ROLE
        with open_checkpointer(engine) as checkpointer:
            assert isinstance(checkpointer.conn, psycopg.Connection)
            row = checkpointer.conn.execute(
                "SELECT current_user, current_setting('search_path') AS path"
            ).fetchone()
        assert row == {"current_user": APP_ROLE, "path": "langgraph"}
    finally:
        engine.dispose()


APP_ROLE_REFUSED = (
    "TRUNCATE audit_events",
    "TRUNCATE security_events",
    "TRUNCATE invoices",
    "DROP TRIGGER audit_events_append_only ON audit_events",
    "DROP TRIGGER security_events_append_only ON security_events",
    "ALTER TABLE audit_events DISABLE TRIGGER audit_events_append_only",
    "DROP FUNCTION audit_events_append_only()",
    "UPDATE audit_events SET reason = 'changed'",
    "DELETE FROM audit_events",
    "UPDATE security_events SET type = 'changed'",
    "DELETE FROM security_events",
    "UPDATE model_calls SET cost_usd = 0",
    "DELETE FROM model_calls",
    "UPDATE alembic_version SET version_num = '0001'",
    "DROP TABLE invoices",
    "ALTER TABLE invoices ADD COLUMN paid boolean",
    "CREATE TABLE public.app_scratch (id int)",
    "CREATE TABLE langgraph.app_scratch (id int)",
    "CREATE INDEX app_scratch ON invoices (created_at)",
    "DROP TABLE langgraph.checkpoints",
    f"ALTER ROLE {APP_ROLE} WITH SUPERUSER",
    "CREATE ROLE app_scratch",
)


@pytest.mark.parametrize("statement", APP_ROLE_REFUSED)
def test_app_role_cannot_change_the_schema_or_the_logs(
    connection: Connection, statement: str
) -> None:
    assert_refused(connection, APP_ROLE, statement)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO audit_events (actor, action, entity_type, entity_id, details) "
        "VALUES ('test', 'test.event', 'test', 'test', '{}')",
        "INSERT INTO security_events (type, severity, details) VALUES ('test', 'low', '{}')",
        "UPDATE suppliers SET name = name",
        "DELETE FROM sessions",
        "SELECT * FROM history_lines",
        "DELETE FROM langgraph.checkpoint_writes",
    ],
)
def test_app_role_reads_and_writes_data(connection: Connection, statement: str) -> None:
    run_as(connection, APP_ROLE, statement)


def test_app_role_has_no_truncate_ownership_or_attributes(engine: Engine) -> None:
    """Holds for every table, also those later migrations add (default privileges)."""
    with engine.connect() as connection:
        truncatable = connection.execute(
            text("SELECT schemaname, tablename FROM pg_tables "
                 "WHERE schemaname IN ('public', 'langgraph') "
                 "AND has_table_privilege(:role, format('%I.%I', schemaname, tablename), "
                 "'TRUNCATE')"),
            {"role": APP_ROLE},
        ).all()  # fmt: skip
        owned = connection.execute(
            text("SELECT relname FROM pg_class WHERE relowner = "
                 "(SELECT oid FROM pg_roles WHERE rolname = :role)"),
            {"role": APP_ROLE},
        ).all()  # fmt: skip
        role = connection.execute(
            text("SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls, rolreplication "
                 "FROM pg_roles WHERE rolname = :role"),
            {"role": APP_ROLE},
        ).one()  # fmt: skip
    assert truncatable == []
    assert owned == []
    assert not any(role)
