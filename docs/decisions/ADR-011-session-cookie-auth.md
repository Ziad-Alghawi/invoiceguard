# ADR-011: Server-side sessions in an HttpOnly cookie, with a lockout

- **Status:** Accepted
- **Date:** 2026-11-13

## Context

ADR-006 decided on seeded email/password users and a session in an HttpOnly cookie, but left open how the
session is represented and how repeated failed logins are handled. The review UI (R1-6) needs both: every
invoice endpoint requires a login, and a reviewer's approve or reject must be tied to that person in the audit
log (ADR-003).

The web app (Next.js) renders on its server and calls the API from there (`API_URL` is server-only). The
browser never talks to the API directly. There is one API process (ADR-007) and one PostgreSQL database.

## Decision

Use **opaque, server-side sessions** stored in PostgreSQL, not JWTs.

- **Login** (`POST /auth/login`) checks the password against an **Argon2id** hash (`argon2-cffi`, library
  defaults, rehash on login when the parameters change). On success it creates a random 256-bit token
  (`secrets.token_urlsafe(32)`), stores only its **SHA-256** in `sessions` with an expiry, and sets the token
  in the cookie `invoiceguard_session`: `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` = session lifetime,
  and `Secure` when `INVOICEGUARD_ENV=prod`.
- **Every request** looks the hash up and checks the expiry; no session → `401`. The lifetime is fixed
  (`INVOICEGUARD_SESSION_TTL_MINUTES`, default 8 hours, a working day); there is no sliding renewal.
- **Logout** deletes the session row, so the token is useless afterwards even if it was copied.
- **Lockout:** `INVOICEGUARD_LOGIN_MAX_FAILURES` (default 5) wrong passwords in a row lock the account for
  `INVOICEGUARD_LOGIN_LOCKOUT_MINUTES` (default 15). While locked, login answers `429` with `Retry-After` and
  does not check the password. A successful login resets the counter. The user row is locked with
  `SELECT ... FOR UPDATE` during login, so parallel attempts cannot each read the same count.
- An unknown email and a wrong password get the same `401` text, and an unknown email still runs one Argon2
  verification, so timing does not tell them apart.
- Login, logout, failed login (with the reason: `wrong_password`, `unknown_email`, `locked`) and the start of a
  lockout are written to `audit_events`. The password never is.
- **Web app (backend for frontend):** a Next.js server action posts the credentials to the API, reads the
  token from the API's `Set-Cookie` and sets the same cookie for the browser on the web origin, with the
  lifetime and `Secure` flag the API chose. Server components and actions forward it to the API as a
  `Cookie` header. A `proxy.ts` check redirects to `/login` when the cookie is missing; the API remains the
  only place that decides whether a session is valid.
- **CSRF:** the browser only posts to the web app, through Next.js server actions, which check the `Origin`
  header. The API cookie is `SameSite=Lax`, and its state-changing endpoints take JSON (or multipart for
  upload, which needs the cookie that a cross-site POST does not send).

## Alternatives

- **Short-lived JWT (with refresh token):** no session table, but logout cannot end a token before it
  expires without a deny list, which is a session table again; key management and rotation add work. We have
  one database already, so a lookup per request costs nothing worth saving.
- **Signed or encrypted cookie holding the user ID (for example iron-session):** stateless, but again no real
  logout, and one more secret to manage.
- **Rate limit per IP address instead of per account:** protects against spraying many accounts, but needs a
  store for counters and real client IPs behind a proxy. Per-account lockout is enough for a demo with a few
  seeded users; see consequences.

## Consequences

- Sessions survive API restarts and can be revoked one by one (delete the row) or all at once.
- One indexed lookup per request; expired rows are deleted at the next login.
- A leaked database does not contain usable tokens or passwords.
- The lockout lets anyone who knows a demo email lock that account for 15 minutes. That is acceptable for the
  demo (the accounts are public anyway, ADR-006); a real deployment would add per-IP limits at the ingress.
- The `429` while locked tells a caller that the email exists. Also accepted for the demo, where the accounts
  are listed; the `401` for wrong credentials does not reveal it.
- Moving to SSO (ADR-006) replaces the login endpoint; sessions, the cookie and the audit rows stay.
