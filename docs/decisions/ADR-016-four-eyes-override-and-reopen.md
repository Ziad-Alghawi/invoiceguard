# ADR-016: Four-eyes override of blocked invoices, and reopening rejected invoices

- **Status:** Accepted
- **Date:** 2026-11-16 (updated 2026-11-17 with R2-3: confirm needs a reason too, one audit row per step,
  how the graph and the endpoints enforce it, seeding)

## Context

ADR-003 says a blocked invoice (for example, an IBAN that differs from the verified registry) can only be
approved with a second confirmation and a written reason. ADR-006 planned a second person for that
confirmation. In R1 (ADR-012) there is one reviewer role, the "second confirmation" is the same reviewer's
written reason, and decisions are final: a wrongly rejected invoice cannot come back, and uploading the
same file again is refused as a duplicate.

Changed bank details are a known fraud pattern because one person can be persuaded to accept them. A
second, independent person is the standard control (separation of duties).

## Decision

**Roles.** `users.role` is `reviewer` or `approver`, checked on the server for every decision. An approver
can do everything a reviewer can.

**Override of a blocked invoice (two steps, two people):**

1. A reviewer requests the override with a written reason. The invoice moves to `override_requested` and
   the graph pauses again (ADR-015). The audit log gets `invoice.override_requested` with the reason and the
   failed checks.
2. A **different** user with the `approver` role confirms it (→ `approved`, audit
   `invoice.override_confirmed`) or declines it (→ `blocked`, audit `invoice.override_declined`), in both
   cases with a written reason of their own, so each step records who decided and why. The person who
   requested the override can never confirm or decline it, whatever their role.

Approving a `ready` invoice stays a one-person decision. Rejecting stays possible in every review state,
including `override_requested`.

**How it is enforced (R2-3).**

- Endpoints: `POST /invoices/{id}/override` (request), `/override/confirm` and `/override/decline`, each
  with a required `reason`. `POST /approve` accepts only `ready` invoices; its R1 field `override_reason`
  is refused (`422`), so an old client cannot approve a blocked invoice alone. A reviewer gets `403` on
  confirm and decline, and so does the requester; a wrong status is `409`.
- Each step is a resume of the paused thread (ADR-015) under the per-invoice advisory lock, and only the
  `decide` node writes the status and **one** audit row, in one transaction (R1 wrote two rows for an
  override: `invoice.override` and `invoice.approved`). After a decision that leaves the invoice in review
  (`override_requested`, or `blocked` after a decline), `decide` routes back to `review`, so the thread
  pauses again; `decide` is still only reachable from `review`.
- The requester is read from the audit log (the latest `invoice.override_requested`), not from the graph
  state, so the rule holds after a restart and for a thread that startup recovery paused again. `decide`
  checks the role and the requester a second time, so a call that skips the endpoint writes nothing.
- Existing users became reviewers (migration 0008). `make seed-user` takes `INVOICEGUARD_SEED_USER_ROLE`
  and, when `INVOICEGUARD_SEED_APPROVER_EMAIL` is set, also seeds that approver.

**Reopening.** Any reviewer can reopen a `rejected` invoice with a written reason
(`POST /invoices/{id}/reopen`, audit `invoice.reopened`). This starts a new graph run with fresh checks,
because master data such as the verified IBAN may have changed, and ends in review again. `approved`
invoices cannot be reopened, because they may already be in a DATEV export. Uploading the same file again
is still refused (409); the response points to the existing invoice.

This supersedes two parts of ADR-012: the single reviewer role and "decisions are final".

## Alternatives

- **Same-user confirmation (R1):** a checkbox and a reason, but one person can still be persuaded; it is
  not four-eyes.
- **Any second user confirms, no approver role:** simpler, but on a real team the confirmation belongs to
  someone with authority to accept a payment risk.
- **Reopen as "undo the decision" without new checks:** faster, but the reviewer would decide on check
  results that may be out of date.
- **Reopen approved invoices too:** would need reversing an export, which happens outside InvoiceGuard.

## Consequences

- No single account can approve a blocked invoice.
- A new status, `override_requested` (18 characters, inside the 20-character status columns of
  `audit_events`).
- The demo seeds a reviewer and an approver and shows both logins on the demo page, so on the public demo
  four-eyes shows the mechanism, not real separation. That is acceptable for sample data, and the README
  says so.
- Reopened invoices have more than one graph run; the audit log, not the thread, is the full history of an
  invoice.
