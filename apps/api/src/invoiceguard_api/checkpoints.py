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
from psycopg.rows import dict_row
from sqlalchemy import Engine, text
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
    """A checkpointer on a new connection to the engine's database, closed afterwards."""
    conninfo = engine.url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(
        conninfo,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        options=f"-c search_path={CHECKPOINT_SCHEMA}",
    ) as connection:
        yield PostgresSaver(connection, serde=JsonPlusSerializer(allowed_msgpack_modules=None))


def lock_invoice(session: Session, invoice_id: uuid.UUID) -> None:
    """Wait for and take the invoice's advisory lock until the session's transaction ends.

    Every graph run and every decision on an invoice takes it first, so work on one thread
    happens one at a time. It locks no rows: graph nodes write the invoice on their own
    connections while the holder waits for them.
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": str(invoice_id)}
    )


@contextmanager
def invoice_lock(session_factory: sessionmaker[Session], invoice_id: uuid.UUID) -> Iterator[None]:
    """Hold the invoice's advisory lock for the block, on a session of its own."""
    with session_factory() as session:
        lock_invoice(session, invoice_id)
        yield
        session.commit()
