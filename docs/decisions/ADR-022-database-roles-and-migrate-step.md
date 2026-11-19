# ADR-022: A restricted database role for the api, migrations as a separate step

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

Until R4-2 the api logged in as the database owner (`POSTGRES_USER`, a superuser in the official PostgreSQL
image) and ran `alembic upgrade head` and `invoiceguard-db-roles` every time its container started. Two problems:

- The audit log and the security log are append-only through a trigger (migrations 0005 and 0009). The owner
  can drop or disable the trigger and can TRUNCATE either table, so a bug or an attacker with the api's
  connection could rewrite history. `docs/status.md` listed this as a known limitation.
- With several api pods (ADR-021), every pod starting at once would run the migrations at once.

PLAN section 11 lists "restricted DB role so the app can't drop the audit trigger or TRUNCATE" for R4, and
ADR-021 decides that migrations run as an Argo CD PreSync Job with the owner role.

## Decision

- **Two kinds of database login.**
  - The **owner** (today `POSTGRES_USER`) owns the schema and runs migrations, `invoiceguard-db-roles` and other
    owner tasks.
  - The api logs in as **`invoiceguard_app`** (migration 0014), which owns nothing. It may read, insert, update
    and delete rows. On `audit_events`, `security_events` and `model_calls` it may only read and insert, and on
    `alembic_version`, the checkpointer's `checkpoint_migrations` and the history views it may only read. It is
    never granted TRUNCATE, it has no CREATE on any schema, and as a non-owner it cannot drop, alter or disable
    tables or triggers.
- **Default privileges** give the app role the same data rights on tables that later migrations create. A later
  append-only table has to revoke UPDATE and DELETE in its own migration. A test checks that no table in
  `public` or `langgraph` lets the role TRUNCATE and that the role owns nothing.
- **The role's password** comes from `INVOICEGUARD_APP_DB_PASSWORD` through `invoiceguard-db-roles`, like the MCP
  roles (ADR-017). The migration creates the role `NOLOGIN`, so no secret is in a migration.
- **Migrations run as a one-shot step**, not at api start. In Compose this is the `migrate` service (the api
  image, the owner's URL, `alembic upgrade head && invoiceguard-db-roles`). The api and the MCP servers start only
  after it has exited successfully (`service_completed_successfully`). In Kubernetes (R4-3) it becomes the
  PreSync Job from ADR-021.
- **Owner tasks run as the owner, never as the app role.** `make demo-reset` runs `invoiceguard-demo-reset` in a
  one-off `migrate` container, and the command refuses to run as `invoiceguard_app`. Anything that would delete
  or truncate audit or security rows belongs there too. The app role is never granted DELETE on the logs to make
  such a task work.
- **Tests run the app as the app role.** The test suite migrates as the owner, and the app under test connects
  with `options=-c role=invoiceguard_app`, so every request and graph run has only the api's real rights without
  changing the role's password (roles belong to the whole server, which the dev stack shares). The compose smoke
  test in CI runs seed, index, uploads, decisions and the demo reset against the real roles.

## Alternatives

- **Keep the owner for the api and rely on the triggers:** nothing to change, but the triggers protect only
  against the app's own UPDATE and DELETE, not against the owner removing them.
- **A non-superuser owner for migrations, now:** better least privilege, but it means reassigning ownership on
  the live demo database, and `CREATE EXTENSION vector` may need a superuser. Left for the Helm chart (R4-3),
  where the database is created fresh.
- **Row-level security or `SECURITY DEFINER` functions for the logs:** finer control, but more moving parts than
  privileges that PostgreSQL already checks on every statement.
- **Migrations at api start behind an advisory lock:** keeps one container, but the api would still need the
  owner's rights to migrate, which is what this ADR removes.

## Consequences

- The api cannot TRUNCATE, run DDL, or change or bypass the append-only triggers; the triggers stay as a second
  layer behind the missing UPDATE and DELETE grants.
- One more secret, `INVOICEGUARD_APP_DB_PASSWORD`. Compose refuses to start without it, so a server `.env` needs
  it before the first deploy of this change (`docs/deploy.md`).
- A migration that adds a table gets data rights for the app automatically; one that needs other rights (an
  append-only log, a read-only table) has to say so, and the role tests should name it.
- The migrator is still the superuser from the PostgreSQL image (known limitation, R4-3).
- Supersedes the part of ADR-017 that sets the MCP passwords at api start: `migrate` sets them now.
