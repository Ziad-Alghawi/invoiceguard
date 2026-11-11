# ADR-003: Human approval is a hard gate

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

InvoiceGuard prepares invoices for booking and payment, and part of it is an AI agent that reads
untrusted documents. Invoice fraud (for example a changed bank account) and prompt injection (text in a
document that tries to instruct the AI) are real threats. If the agent could pay, post a booking or change
master data, one successful attack or one model mistake could move money.

An approval step that exists only in the user interface is not enough: a bug, a direct API call or a
manipulated agent could skip it. The gate must be part of how the workflow runs, and dangerous actions
must be impossible, not just discouraged.

## Decision

1. **Approval is a pause in the workflow itself.** The processing graph is built with LangGraph. Before
   anything is marked approved, the graph calls `interrupt()` and stops. Its state is saved by the
   LangGraph PostgreSQL checkpointer, so the pause survives restarts and can wait for days.
2. **Only an authenticated human can resume it.** Resuming the graph requires an approve, reject or edit
   action from a logged-in user. Who decided, what, when and why is written to an audit log. There is
   no auto-approve path.
3. **Blocked invoices need more.** If the bank account on an invoice does not match the verified account,
   the invoice is blocked and can only be approved with a second confirmation and a written reason.
4. **No tool that pays, posts or writes exists.** The agent's tools are read-only: look up suppliers,
   purchase orders, verified bank accounts, similar invoices and rules, and draft an email for a human
   to send. There is no tool that makes payments, posts bookings or writes to an ERP system or the
   supplier registry. The final output is an export file that a person imports into their own system.

These rules are enforced in code and covered by tests.

## Alternatives

- **Approval only in the UI (a button that sets a status):** easy to bypass by bug or direct API call.
- **Write tools guarded by a confirmation prompt:** the tool still exists, so a manipulated agent or a
  bug could call it.
- **Auto-approve low-risk invoices:** saves time, but creates exactly the path attackers look for.
- **Custom pause/resume with a status column:** possible, but reinvents durable state that LangGraph
  checkpoints already provide.

## Consequences

- A compromised or wrong agent can at worst produce a bad suggestion, which a human sees before anything
  happens.
- Every invoice needs a human action, which limits throughput; this is intended.
- Checkpoint tables live in PostgreSQL and need the same backups and migrations as business data.
- Connecting to a real ERP later means a human-triggered export or import, never an agent tool. Changing
  that would need a new ADR that supersedes this one.
