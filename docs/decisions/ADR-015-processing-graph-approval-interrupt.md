# ADR-015: Processing graph with LangGraph, approval as `interrupt()`

- **Status:** Accepted
- **Date:** 2026-11-16 (updated 2026-11-16 with R2-2: own schema, every run pauses at review, failed resumes)

## Context

ADR-003 requires approval to be a pause in the workflow itself, stored durably and resumed only by an
authenticated person. R1 deferred this (ADR-012): processing is a background task with a status column
(ADR-007), and approve and reject are status changes made by the API. R2 adds steps after the checks (an
exception agent, a second approver), so the flow needs one place that holds its state between steps and
across restarts.

Constraints: the app uses synchronous SQLAlchemy with psycopg 3 (ADR-008); the status column is what the
UI, the queue filter, the DATEV export and the tests read; the existing approve and reject endpoints and
their rules must keep working.

## Decision

Processing becomes **one LangGraph graph per invoice**, with its state saved by the **LangGraph PostgreSQL
checkpointer** (`PostgresSaver`, sync) in the application database, in a schema of its own (`langgraph`).

- **Nodes:** `read` (XML parse and KoSIT) or `extract` (LLM extraction) → `checks` → `review` → `decide`. A
  file that cannot be read (`failed`) or a PDF without XML (`awaiting_extraction`) goes from `read` straight to
  `review`. The thread ID is the invoice ID; a later run of the same invoice (reopen, ADR-016) gets its own
  thread (`{invoice_id}:{run}`).
- **Every run ends paused at `review`**, whatever its outcome: reject accepts `ready`, `blocked`, `failed` and
  `awaiting_extraction` invoices, so each of them needs a paused thread to resume. Extraction after waiting is a
  new run on the same thread: new input starts a thread again from START, which drops the pending pause.
- **The pause:** `review` calls `interrupt()` as its first statement. LangGraph runs a node again from its
  start when it resumes, so nothing may happen in that node before the pause. `decide` is reachable only from
  `review`, and START routes only to `read`, `extract` or `review`; a test checks the edges.
- **Resuming:** `POST /invoices/{id}/approve` and `/reject` keep their paths, request bodies, rules and
  responses. They take a transaction-scoped advisory lock on the invoice (`pg_advisory_xact_lock`), check the
  user and the rules, and resume the thread with `Command(resume=...)`. The resume runs synchronously, so the
  response already shows the new status. **Every graph run takes the same lock** (after upload, extraction,
  startup recovery), so a run and a decision never work on one thread at the same time.
- **Writing the outcome:** the `decide` node writes the status and the audit rows in one transaction of its
  own. It refuses (and writes nothing) if the status is no longer the one the reviewer decided on. The endpoint
  does not hold a row lock (`SELECT ... FOR UPDATE`) while resuming: the graph writes the same row through
  another connection, and the two would wait for each other.
- **Failed resume:** if `decide` fails after the thread has resumed, the thread is past `review` with the old
  decision in its state, and a plain `Command(resume=...)` would be ignored (nothing is paused). So before each
  resume the endpoint checks that the thread is paused at `review` and, if not, starts a run at `review` first.
  The retry then decides with the new request's values, never the failed one's.
- **Status column:** stays the read model for the UI and the queries (ADR-007). Graph nodes write every final
  status. Two writes stay in front of the graph: the claim (a conditional update to `processing`, which decides
  which caller runs the graph) and the startup reset of `processing` to `received`. The daily budget deferral
  writes only the reason, not the status.
- **Execution:** `BackgroundTasks` still start the graph after upload and extraction (ADR-007 stays; only
  what the task runs changes). The app's services (session factory, storage, validator, extractor) go to each
  run as LangGraph's run context; they are never checkpointed. Startup recovery resets and re-runs unfinished
  invoices as before, and starts a run at `review` for every invoice waiting for review whose thread is not
  paused there: invoices that were `ready` or `blocked` before this change, and threads left behind a decision
  that failed.
- **Tables:** the checkpointer's tables are created by Alembic migration 0007, which calls the checkpointer's
  own setup with `search_path` set to `langgraph`, so the schema is versioned with ours. The own schema keeps
  the application schema to exactly our models (a test checks that) and makes the checkpoint data easy to find,
  back up or drop. Each run opens a psycopg connection of its own with autocommit (the checkpointer's setup
  creates indexes `CONCURRENTLY`, and it expects autocommit). The serializer is strict (built-in types only):
  the state is plain JSON (invoice ID, the read invoice for the checks, the decision), so a row written into
  the checkpoint tables cannot make the API build arbitrary objects. The demo reset deletes the threads of the
  invoices it deletes.

R2-2 introduces the graph **without changing behaviour**: the same statuses, rules, audit events and
responses, and the existing tests pass unchanged. The four-eyes override (ADR-016) and the agent follow in
later changes.

## Alternatives

- **Keep the R1 status endpoints:** simple, but approval stays a status change that a bug or a direct call
  can set; this is what ADR-003 rules out.
- **An own pause/resume on the status column:** possible, but rebuilds the durable state and resume logic
  the checkpointer already provides; rejected in ADR-003.
- **`AsyncPostgresSaver`:** the rest of the app uses sync database access (ADR-008); mixing both models adds
  a second connection style for no gain at this load.
- **A row lock in the endpoint around the resume:** deadlocks with the node that updates the same row.

## Consequences

- An invoice can only reach `approved` or `rejected` through a resumed thread; a test calls the graph
  without a resume and shows it stays paused.
- A pause survives API restarts and can last for days.
- Status and checkpoint are separate writes. If a resume fails, the status has not changed and the request
  can be repeated; a test covers this.
- Startup reads the thread of every invoice waiting for review (one query each). Fine for the demo; with
  many waiting invoices it should only look at threads that are not paused.
- A decision waits while a run holds the invoice's lock, for example during an LLM extraction (seconds).
  Since R4-2 it waits at most `INVOICEGUARD_DECISION_LOCK_TIMEOUT_MS` (default 2 s, PostgreSQL's
  `lock_timeout` for the lock statement only) and then answers `409`, so a request never hangs behind an
  extraction, whichever api pod runs it.
- Checkpoint tables need the same backups and migrations as business data, and add a few kilobytes per
  invoice.
- New dependencies: `langgraph` and `langgraph-checkpoint-postgres` (named in the plan and in ADR-003; the
  checkpointer uses psycopg 3, which the app already uses). Pinned to `langgraph` 1.2.20 and
  `langgraph-checkpoint-postgres` 3.2.0, with `langgraph-checkpoint` held at 4.3.1: the newer releases were
  two to four days old. A checkpointer update that adds setup steps needs a new migration that calls its setup
  again.
