# ADR-012: Review decisions in R1: a status change by one reviewer, override with a reason

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

R1 needs a working review: a reviewer opens an invoice, sees fields and check results, and approves or
rejects it. Two earlier decisions describe the full design, which arrives with the agent in R2:

- ADR-003: approval is an `interrupt()` in the LangGraph graph, resumed by an authenticated user; a blocked
  invoice needs a second confirmation and a written reason.
- ADR-006: demo users have roles, including a second person for that extra confirmation.

In R1 there is no graph yet (processing is a background task with a status column, ADR-007), and the R1 task
asks for a single reviewer role. ADR-007 also said review outcomes would not be stored in the status column.
We need a decision for R1 that keeps the hard rules of ADR-003 without building R2 now.

## Decision

In R1, a decision is **a status change made by the API in one transaction**, with these rules:

- Two new final statuses, `approved` and `rejected`, set only by `POST /invoices/{id}/approve` and
  `POST /invoices/{id}/reject` for a logged-in user (ADR-011). Processing never touches them: it only moves
  invoices it has claimed from `received` or `awaiting_extraction`.
- **Approve** works on `ready`, and on `blocked` only with a non-empty `override_reason`. Approving a
  `ready` invoice with an override reason is refused (nothing to override). **Reject** needs a non-empty
  reason and works on `ready`, `blocked`, `failed` and `awaiting_extraction`; not while `received` or
  `processing`, because the background task would overwrite the decision. Decisions are final in R1.
- The invoice row is locked (`SELECT ... FOR UPDATE`) while deciding, so two reviewers clicking at once
  cannot both decide.
- **One reviewer role.** The "second confirmation" for a blocked invoice is, in R1, the same reviewer's
  explicit override: a written reason in the API, plus a confirmation checkbox in the UI. There is no second
  person yet.
- **Audit:** `audit_events` (created in migration 0001 and already written by upload and processing) gets
  columns for the user, the status before and after, and the reason, and a database trigger that rejects
  `UPDATE` and `DELETE`. An override writes `invoice.override` (reason and the failed checks) followed by
  `invoice.approved`; reject writes `invoice.rejected`. `GET /invoices/{id}/audit` returns the history. We
  extend this table instead of adding a second audit table, so one invoice's history stays in one place.

This supersedes the sentence in ADR-007 that review outcomes are not part of the status, and defers, not
drops, two parts of ADR-003 and ADR-006 (below).

## Alternatives

- **Build the LangGraph `interrupt()` now:** the right end state, but R2 builds the graph, the checkpointer
  and the agent together; doing the pause alone now means building it twice.
- **A separate `decisions` table and a `review_status` column:** cleaner separation of processing and
  review, but two status fields to keep consistent and filter on, for no gain while the decision is final and
  single-step.
- **Two roles with a second approver for overrides now:** closer to ADR-006, but the R1 scope is one role, and
  a second approver only makes sense with a "pending second approval" state, which is the R2 graph's job.

## Consequences

- R1 has the hard rules that matter most: no approval without a logged-in person, no approval of a blocked
  invoice without a written reason, and a log that the application cannot rewrite.
- **Open for R2:** approval moves into the graph (`interrupt()` and resume, ADR-003), and overriding a
  blocked invoice needs a second person with an approver role (ADR-006). The API endpoints stay; they will
  resume the graph instead of setting the status.
- The trigger stops the application and anyone using its database user from changing or deleting audit rows.
  It does not stop the table owner from dropping the trigger or truncating the table; a production setup
  would give the application a database role without those rights.
- Rejected invoices cannot be reopened in R1; uploading the same file again is refused as a duplicate (409).
