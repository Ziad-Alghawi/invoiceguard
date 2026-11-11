# ADR-008: Synchronous SQLAlchemy 2 with psycopg 3

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

R1 adds PostgreSQL to the API: SQLAlchemy 2 for the models, Alembic for migrations, psycopg 3 as the
driver. SQLAlchemy 2 offers a synchronous and an asyncio API, and FastAPI supports both `def` and
`async def` endpoints. The choice affects every endpoint, every background task and every test.

Facts that matter here:

- ADR-007 runs processing as FastAPI `BackgroundTasks` and already requires blocking work (PDF
  parsing, the KoSIT validator call) to run in the thread pool.
- FastAPI runs `def` endpoints and synchronous background tasks in that thread pool on its own.
- The load is a handful of invoices at a time (ADR-007); evaluations run from a CLI.
- Alembic runs synchronously; with an async engine its `env.py` needs an extra bridge.
- The LangGraph PostgreSQL checkpointer (R2) has both a sync and an async variant.

## Decision

Use the **synchronous** SQLAlchemy 2 API with the **psycopg 3** driver (`postgresql+psycopg://`).

- Endpoints that touch the database are plain `def` functions and get a request-scoped `Session`
  through a FastAPI dependency.
- The engine uses `pool_pre_ping` and a short connect timeout, so `/ready` answers quickly when the
  database is down.
- Models use SQLAlchemy 2's typed `Mapped[...]` style; the schema is owned by Alembic migrations, and a
  test fails when models and migrations differ.

## Alternatives

- **Async SQLAlchemy (`AsyncSession`, asyncpg or psycopg async):** scales better for many concurrent,
  I/O-bound requests, which we do not have. It adds lazy-loading pitfalls (`MissingGreenlet`), an async
  Alembic bridge, async test fixtures, and it would still need the thread pool for the blocking PDF and
  XML work.
- **psycopg2 instead of psycopg 3:** in maintenance mode; psycopg 3 is the current driver and ships
  binary wheels, so the slim image needs no system libpq.
- **asyncpg:** only for async; fastest driver, but not needed for this load.

## Consequences

- Each request holds a thread from FastAPI's pool (40 by default) while it waits on the database.
  That is far above the demo's load; revisit if API latency under load shows thread-pool saturation.
- Code reads top to bottom without `await`, and tests use a plain `Session` against a real PostgreSQL.
- Moving to async later changes the session dependency and the endpoint signatures, not the models or
  the migrations.
