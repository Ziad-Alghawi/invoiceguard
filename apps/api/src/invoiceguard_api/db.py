"""Database engine and request-scoped sessions.

Sync SQLAlchemy (ADR-008): FastAPI runs `def` endpoints and background tasks in its thread pool.
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str) -> Engine:
    # pre_ping replaces connections the database closed (for example after a db restart).
    # A short connect timeout keeps /ready from hanging when the database is unreachable.
    return create_engine(database_url, pool_pre_ping=True, connect_args={"connect_timeout": 3})


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def ping(engine: Engine) -> None:
    """Raise if the database cannot answer a trivial query."""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def get_session(request: Request) -> Iterator[Session]:
    session_factory: sessionmaker[Session] = request.app.state.session_factory
    with session_factory() as session:
        yield session


DbSession = Annotated[Session, Depends(get_session)]
