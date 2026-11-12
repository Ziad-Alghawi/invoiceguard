# ADR-007: Background execution with FastAPI BackgroundTasks and a status column

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

After an invoice is uploaded, processing takes from milliseconds (XML parse and checks) to tens of
seconds (PDF extraction by an LLM, KoSIT validation, later the exception agent). The upload request
should not wait for all of that, and the review queue must show where each invoice is.

The demo handles a handful of invoices at a time. Evaluation runs process hundreds, but they run from a
CLI, not through the upload endpoint. Every extra service (a broker, a worker) must be built, deployed,
monitored and kept alive on free or cheap hosting.

## Decision

Start with **FastAPI `BackgroundTasks`** and a **status column on `invoices`**.

- The upload endpoint stores the file, creates the invoice with status `received`, schedules processing
  as a background task and returns `202 Accepted` with the invoice ID.
- The task sets `processing`, runs parse, validation and checks, and ends in `ready` (clean, waiting for
  review) or `blocked` (a hard rule failed, for example the IBAN does not match the registry). If
  processing raises, the invoice ends in `failed` with the error recorded, so nothing hangs silently.
- Each status change is a single database update, so the status is always the source of truth for the
  UI, which polls it.
- Review outcomes (approved, rejected) are recorded by the approval workflow (ADR-003), not by this
  status.
- On startup, invoices left in `processing` by a restart are reset to `received` and scheduled again.
  Processing steps must therefore be safe to run twice.

**Move to a worker** (a separate process reading jobs from PostgreSQL, or a small queue library) only
when one of these is measured:

- Upload or other API requests get slower because background work competes with them.
- Invoices are lost or stuck because the API process restarts during long LLM calls.
- Evaluations or the n8n mailbox flow need to push work through the API faster than one process handles.

## Alternatives

- **Celery or RQ with Redis:** proven, with retries and scheduling, but adds Redis and a worker
  deployment for a load we do not have.
- **A PostgreSQL-backed job queue (for example `SELECT ... FOR UPDATE SKIP LOCKED` or a library on top of
  it):** the likely next step because it needs no new infrastructure; not needed yet.
- **Synchronous processing in the request:** simplest, but PDF extraction would hold the request for
  many seconds and time out on some hosts.

## Consequences

- No new infrastructure: the API process does the work, which keeps the R1 deploy simple.
- Background tasks share the API's CPU and event loop; blocking work (PDF parsing) must run in a thread
  pool, not in the event loop.
- There are no automatic retries; a `failed` invoice is retried by a user action.
- The status column and the idempotent steps carry over unchanged if a worker is added later; only who
  picks up `received` invoices changes.

## Amendment (2026-11-12)

- New status `awaiting_extraction`: a PDF without embedded e-invoice XML waits there for LLM extraction (R1-5).
  It is not `received`, so startup recovery does not pick it up again on every restart.
- New column `invoices.status_reason`: why an invoice is in its status (for example the parse error of a `failed`
  invoice), shown to the user. Internal errors get a generic reason; the details go to the logs.
- Startup recovery runs in the thread pool after the app has started, so the API answers while it works.
