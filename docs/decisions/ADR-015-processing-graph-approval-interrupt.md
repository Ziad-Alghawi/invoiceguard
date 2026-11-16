# ADR-015: Processing graph with LangGraph, approval as `interrupt()`

- **Status:** Accepted
- **Date:** 2026-11-16

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
checkpointer** (`PostgresSaver`, sync) in the application database.

- **Nodes:** read (XML parse or LLM extraction) → checks → `review` → `decide`. The thread ID is the invoice
  ID; a later run of the same invoice (reopen, ADR-016) gets its own thread (`{invoice_id}:{run}`).
- **The pause:** `review` calls `interrupt()` as its first statement. LangGraph runs a node again from its
  start when it resumes, so nothing may happen in that node before the pause.
- **Resuming:** `POST /invoices/{id}/approve` and `/reject` keep their paths, request bodies, rules and
  responses. They check the user and the rules, take a transaction-scoped advisory lock on the invoice
  (`pg_advisory_xact_lock`) so that two decisions on one invoice run one after the other, and resume the
  thread with `Command(resume=...)`. The resume runs synchronously, so the response already shows the new
  status.
- **Writing the outcome:** the `decide` node writes the status and the audit rows in one transaction of its
  own. The endpoint does not hold a row lock (`SELECT ... FOR UPDATE`) while resuming: the graph writes the
  same row through another connection, and the two would wait for each other.
- **Status column:** stays the read model for the UI and the queries (ADR-007). Only graph nodes write it.
- **Execution:** `BackgroundTasks` still start the graph after upload and extraction (ADR-007 stays; only
  what the task runs changes). Startup recovery resumes or restarts unfinished threads. Invoices that were
  `ready` or `blocked` before this change get a thread that starts at `review`.
- **Tables:** the checkpointer's tables are created by an Alembic migration that calls the checkpointer's
  own setup, so the schema is versioned with ours. The demo reset clears them together with the invoices.

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
- Checkpoint tables need the same backups and migrations as business data, and add a few kilobytes per
  invoice.
- New dependencies: `langgraph` and `langgraph-checkpoint-postgres` (named in the plan and in ADR-003; the
  checkpointer uses psycopg 3, which the app already uses).
