"""The LangGraph checkpointer and the per-invoice lock (ADR-015).

Checkpoints live in their own schema of the application database, created by migration 0007
with the checkpointer's own setup. The checkpointer needs an autocommit connection (its setup
creates indexes CONCURRENTLY), so each graph run opens a psycopg connection of its own next to
the SQLAlchemy pool.

The serializer only restores built-in types (strict msgpack): the graph state is plain JSON
values, and a row written into the checkpoint tables cannot make the API build arbitrary objects.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.errors import LockNotAvailable
from psycopg.rows import dict_row
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

CHECKPOINT_SCHEMA = "langgraph"
CONNECT_TIMEOUT_SECONDS = 3


def engine_of(session_factory: sessionmaker[Session]) -> Engine:
    bind = session_factory.kw.get("bind")
    if not isinstance(bind, Engine):
        raise TypeError("The session factory must be bound to an engine.")
    return bind


@contextmanager
def open_checkpointer(engine: Engine) -> Iterator[PostgresSaver]:
    """A checkpointer on a new connection to the engine's database, closed afterwards.

    Server options in the database URL (`?options=...`) are kept: the search path is added to
    them, since a keyword argument would replace the URL's value.
    """
    url = engine.url.set(drivername="postgresql")
    given = url.query.get("options", ())
    given = (given,) if isinstance(given, str) else tuple(given)
    options = " ".join((*given, f"-c search_path={CHECKPOINT_SCHEMA}"))
    with psycopg.connect(
        url.difference_update_query(["options"]).render_as_string(hide_password=False),
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        options=options,
    ) as connection:
        yield PostgresSaver(connection, serde=JsonPlusSerializer(allowed_msgpack_modules=None))


class InvoiceBusy(Exception):
    """Another session held the invoice's lock for longer than the caller would wait."""


def lock_invoice(session: Session, invoice_id: uuid.UUID, timeout_ms: int | None = None) -> None:
    """Wait for and take the invoice's advisory lock until the session's transaction ends.

    Every graph run and every decision on an invoice takes it first, so work on one thread
    happens one at a time, also across api pods (they share the database). It locks no rows:
    graph nodes write the invoice on their own connections while the holder waits for them.

    With `timeout_ms`, waiting longer raises `InvoiceBusy` (PostgreSQL's `lock_timeout`, set
    for this one statement); the transaction is then rolled back.
    """
    if timeout_ms is not None:
        session.execute(
            text("SELECT set_config('lock_timeout', :timeout, true)"),
            {"timeout": f"{timeout_ms}ms"},
        )
    try:
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": str(invoice_id)},
        )
    except OperationalError as error:
        if not isinstance(error.orig, LockNotAvailable):
            raise
        session.rollback()
        raise InvoiceBusy(str(invoice_id)) from error
    if timeout_ms is not None:
        # Later statements of the transaction wait as usual.
        session.execute(text("SET LOCAL lock_timeout = DEFAULT"))


def try_lock_invoice(session: Session, invoice_id: uuid.UUID) -> bool:
    """Take the invoice's advisory lock (as `lock_invoice`) if it is free; never waits."""
    locked: bool = session.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": str(invoice_id)},
    )
    return locked


@contextmanager
def invoice_lock(
    session_factory: sessionmaker[Session], invoice_id: uuid.UUID, *, wait: bool = True
) -> Iterator[bool]:
    """Hold the invoice's advisory lock for the block, on a session of its own.

    Yields True. With `wait=False` it yields False at once while another session (a run or a
    decision, maybe in another pod) holds the lock; the block then must not touch the invoice.
    """
    with session_factory() as session:
        if wait:
            lock_invoice(session, invoice_id)
        elif not try_lock_invoice(session, invoice_id):
            yield False
            return
        yield True
        session.commit()
