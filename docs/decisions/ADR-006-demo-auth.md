# ADR-006: Demo authentication with seeded email/password users

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

Human approval is a hard gate (ADR-003): only an authenticated user can approve, reject or edit an
invoice, and every decision is written to the audit log with who made it. The public demo therefore
needs real authentication, with at least two roles: a reviewer who decides on invoices, and a second
person for the extra confirmation that blocked invoices require.

The demo is for recruiters and reviewers who want to try it in under a minute. There is no budget for
paid services, and the project should not depend on sending email.

## Decision

Use **email and password login with users seeded by a migration or seed script**. There is no sign-up.

- Demo accounts and their roles are created by a seed command; their passwords come from env config and
  are shown on the demo login page, because they are meant to be shared.
- Passwords are stored only as hashes with a standard password-hashing algorithm (Argon2id or bcrypt).
- The API issues a session in an HttpOnly, Secure, SameSite cookie; the web app never stores tokens in
  JavaScript-readable storage.
- Every write action checks the role on the server. The UI hiding a button is not a permission check.
- Demo data can be reset by re-running the seed, so visitors cannot leave it in a broken state for long.

## Alternatives

- **Magic link:** no passwords to manage, but needs an email service (setup, deliverability, a sending
  domain) and makes a visitor wait for an email before seeing anything.
- **OAuth / SSO (GitHub, Google, Entra ID):** realistic for companies, but every visitor would need an
  account with that provider, and roles still need our own table. Kept in the backlog.
- **No login, role picker in the UI:** fastest to try, but breaks ADR-003, because decisions would not
  be tied to an authenticated person.

## Consequences

- No external service is needed; the demo works offline and in CI, including the Playwright tests.
- Shared demo passwords mean the demo accounts are not secret. That is fine for seeded demo data and
  must never be reused for real data.
- We own session handling and must test it: login, logout, expired session, wrong role on approve.
- Moving to SSO later replaces the login step only; roles, audit log and server-side checks stay.
