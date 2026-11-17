# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Four-eyes override (R2-3, ADR-016): user roles `reviewer` / `approver` and the status `override_requested`
  (migration 0008, existing users become reviewers). `POST /invoices/{id}/override` (any user, reason required),
  `/override/confirm` and `/override/decline` (a different user with the approver role, reason required; `403`
  for reviewers and the requester). Each step resumes the paused graph thread under the per-invoice lock, and the
  `decide` node writes the status and one audit row (`invoice.override_requested`, `invoice.override_confirmed`,
  `invoice.override_declined`), checking the role and the requester again. `GET /auth/me` returns the role.
  `make seed-user` also seeds an approver from `INVOICEGUARD_SEED_APPROVER_*` and takes
  `INVOICEGUARD_SEED_USER_ROLE`. Web: override request, confirm and decline in the decision panel, role in the
  header, "Override requested" queue tab, both demo accounts on the login page (`DEMO_APPROVER_*`). Playwright
  test for the override flow.
- `make deploy`: pulls `main` and runs `make prod-up` on the demo server over SSH; the target comes from
  `DEPLOY_HOST` in the local `.env`, and the command refuses to run without it (`docs/deploy.md` section 6).
- Processing graph (R2-2, ADR-015): processing runs as a LangGraph graph per invoice (`read` / `extract` → `checks` →
  `review` → `decide`, thread ID = invoice ID), checkpointed by `PostgresSaver` in the `langgraph` schema (migration
  0007). Every run pauses at `review` with `interrupt()`; approve and reject resume it with `Command(resume=...)`
  under a per-invoice advisory lock, and only `decide` writes `approved` / `rejected` with its audit rows. Pauses
  survive API restarts; startup gives invoices from before the graph a paused thread; the demo reset deletes
  threads. Same statuses, rules, responses and audit events as before. Dependencies `langgraph` 1.2.20 and
  `langgraph-checkpoint-postgres` 3.2.0.
- ADR-015 (processing graph with LangGraph, approval as `interrupt()`) and ADR-016 (four-eyes override of blocked
  invoices, reopening rejected invoices); R2 plan in `docs/status.md`.
- Public demo deployment (ADR-014, `docs/deploy.md`): `infra/edge` is a shared Caddy for every site on the server
  (the only public ports, automatic Let's Encrypt HTTPS, shared security headers, no access log, one file per site);
  `infra/docker-compose.prod.yml` removes all host ports, attaches the web container to its `edge` network, sets
  `INVOICEGUARD_ENV=prod` for Secure cookies, restart policies, log rotation and a 1 GB memory limit for the
  validator. `make prod-up`, `make prod-down`, `make demo-reset`.
- Daily LLM budget (`INVOICEGUARD_LLM_DAILY_BUDGET_USD`, summed from `model_calls` per UTC day): once reached, PDFs stay
  in `awaiting_extraction` with a reason and an `invoice.extraction_deferred` audit event, without calling the model.
- Demo reset (`invoiceguard-demo-reset`, only with `INVOICEGUARD_DEMO_MODE=true`): deletes invoices, exports and
  files, keeps the append-only audit log (plus a `demo.reset` event) and LLM costs, restores the master data and
  processes five packaged sample invoices (ready, changed IBAN, PO overcharge, CII, unknown supplier).
- Web: the login page shows the shared demo account when `DEMO_LOGIN_EMAIL` and `DEMO_LOGIN_PASSWORD` are set.
- CI: validates the prod override, the shared Caddy and its sites, and runs the demo reset in the built image.
- README: description, demo link, screenshots, architecture diagram, features, tech stack, honest limits.

- DATEV-style export (ADR-013): `POST /exports/datev` writes the approved, not yet exported invoices of the oldest
  waiting fiscal year into an `EXTF` Buchungsstapel file (format 700/13, Windows-1252, CRLF, `;`, decimal comma, DDMM
  document date, one row per invoice: gross amount, Soll/Haben, creditor and expense account, BU key for a single
  configured VAT rate, Belegfeld 1, Buchungstext) and returns the count, how many have no tax key and how many are
  left for another fiscal year; `GET /exports/datev/{id}/file` downloads the stored file again. Settings
  `INVOICEGUARD_DATEV_*` (advisor and client number, fiscal year start, account length, chart, accounts, tax keys as
  JSON). Audit events `datev_export.created`, `invoice.exported`, `datev_export.downloaded`.
- Migration 0006: `datev_exports` (the stored files) and `invoices.datev_export_id`; exports lock the invoices
  `FOR UPDATE`, so an invoice is never in two files.
- Web: "Export to DATEV" on the queue starts the download and shows the count, with "Download again".
- Playwright end-to-end test (`make e2e`, CI job `e2e` on Docker Compose, no LLM calls): login, reject the
  changed-IBAN invoice, approve a clean one, export and check the downloaded file. `@playwright/test` 1.64.1
  (pinned; the newer 1.65 releases were days old).
- Tests: DATEV field formatting, encoding and a golden file; export rules (no double export, only approved, one
  fiscal year per file, tax keys, settings, parallel exports, audit).

- Login with seeded users (ADR-006, ADR-011): `POST /auth/login`, `/auth/logout`, `GET /auth/me`; Argon2id password
  hashes (`argon2-cffi`); server-side sessions (only the token's SHA-256 is stored) in an HttpOnly, SameSite=Lax cookie,
  Secure in prod; 5 failed logins in a row lock the account for 15 minutes (`429` with `Retry-After`). Settings
  `INVOICEGUARD_SESSION_TTL_MINUTES`, `INVOICEGUARD_LOGIN_MAX_FAILURES`, `INVOICEGUARD_LOGIN_LOCKOUT_MINUTES`.
- `invoiceguard-seed-user` / `make seed-user`: creates or resets a user from `INVOICEGUARD_SEED_USER_*`; the password
  comes from the environment only.
- Review API (ADR-012): every invoice endpoint needs a login; `POST /invoices/{id}/approve` (a `blocked` invoice only
  with `override_reason`), `POST /invoices/{id}/reject` (reason required), statuses `approved` and `rejected`;
  `GET /invoices` filters by `status` and returns `X-Total-Count`; `GET /invoices/{id}` returns the fields with
  `low_confidence` flags and a `file_url`; `GET /invoices/{id}/file` downloads the original; `GET /invoices/{id}/audit`.
- Migration 0005: `users`, `sessions`, the two review statuses, and on `audit_events` the user, status before and
  after and reason as columns (existing status events moved there) plus a trigger that rejects `UPDATE` and `DELETE`.
  Login, logout, failed login, lockout, upload (now attributed to the user), override, approve and reject are audited.
- Web review UI: login page, queue with status filters and paging, invoice page with check results, extracted fields
  (low-confidence ones highlighted with evidence), download, approve / approve with override / reject, and audit
  history; the web server forwards the session to the API (backend for frontend).
- CI smoke test logs in with a generated seed password and approves, overrides and checks the audit rows.
- ADR-011 (sessions and lockout), ADR-012 (review decisions in R1), ADR-007 amendment (review statuses).
- LLM extraction of plain PDF invoices (ADR-010): Gemini Flash reads the PDF and answers in a strict schema with a
  value, confidence and evidence (page, snippet) per field and per line; one retry on invalid output, then
  `failed`; fields stored with `source=llm`. Flow `awaiting_extraction → processing → ready / blocked / failed`
  with an atomic claim, audit events and startup recovery; without an API key PDFs wait with a reason.
- `LLMClient` interface with a LiteLLM implementation (ADR-004); LiteLLM 1.108.1 pinned, its bundled price table
  only (no download at import), and no `.env` loading at import (`LITELLM_MODE=PRODUCTION`).
- `low_confidence` check: fields below `INVOICEGUARD_EXTRACTION_CONFIDENCE_THRESHOLD` warn; a low-confidence payee
  IBAN or total blocks the invoice.
- Cost log: migration 0004 with `model_calls` (tokens, cost, latency, status per call, also failed ones) and
  `invoice_fields.evidence`; an unknown model price fails the extraction; `GET /invoices/{id}` returns `llm_calls`
  and `llm_cost_usd`.
- Prompt-injection boundary for extraction: constant system prompt, document only between untrusted markers in the
  user message, schema with no extra keys, rejection reasons without document text; tested with an injection PDF.
- `scripts/extract_pdfs.py`: manual run against the real model with fields, confidence, cost and time per PDF.
- Settings `INVOICEGUARD_LLM_API_KEY`, `INVOICEGUARD_EXTRACTION_MODEL`, `INVOICEGUARD_LLM_TIMEOUT_SECONDS`,
  `INVOICEGUARD_EXTRACTION_CONFIDENCE_THRESHOLD`, `INVOICEGUARD_EXTRACTION_REASONING_EFFORT` (thinking level,
  default `low`); empty environment variables now count as unset.
- Monorepo skeleton (`apps/`, `services/`, `packages/`, `infra/`, `workflows/`, `docs/decisions/`) with a purpose README per folder.
- MIT licence, README skeleton, `CLAUDE.md`, `docs/status.md`, `.gitignore`, `.env.example`, `.editorconfig`.
- ADR template and ADR-001 (stack), ADR-002 (code vs LLM boundary), ADR-003 (approval as hard gate), linked from the README.
- `apps/api` uv project (Python 3.12, FastAPI) with `GET /health` and `GET /ready`, env-based settings (pydantic-settings), JSON logging, and ruff, mypy (strict) and pytest with coverage.
- `apps/web` pnpm project (Next.js App Router, TypeScript strict, Tailwind, shadcn/ui) with a home page that shows the API `GET /health` status (`ok` / `unreachable`) from the server-only `API_URL`, read per request, and eslint, prettier and vitest.
- Multi-stage, non-root Dockerfiles for `apps/api` (uv, python slim) and `apps/web` (Next.js standalone output, `API_URL` read at runtime).
- Docker Compose stack in `infra/` (api, web, db with `pgvector/pgvector:pg16`) with healthchecks; web starts after the api is healthy; configured from the root `.env`.
- Root `Makefile` with `dev`, `down`, `check`, `test` and `eval` (placeholder until R3).
- pre-commit hooks: ruff, ruff-format, prettier, end-of-file-fixer, trailing-whitespace, check-added-large-files, detect-secrets with a baseline.
- GitHub Actions CI (`api`, `web`, `compose-smoke` jobs) on pull requests and pushes to `main`, a pull request template and a CI badge.
- ADR-004 (model router: LiteLLM SDK behind an own interface), ADR-005 (ZUGFeRD/XRechnung reading: factur-x for PDF extraction plus an own lxml parser, with spike results), ADR-006 (demo auth: seeded email/password users), ADR-007 (background execution: FastAPI BackgroundTasks and an invoice status column).
- Database layer in `apps/api`: SQLAlchemy 2 (sync, typed models) with psycopg 3, Alembic migrations, `INVOICEGUARD_DATABASE_URL` setting; ADR-008 records the sync choice.
- First migration with the R1 tables: `invoices`, `invoice_fields`, `suppliers`, `supplier_bank_accounts`, `purchase_orders`, `purchase_order_lines`, `checks`, `audit_events`.
- `make seed` (`invoiceguard-seed`): idempotent German demo data with 5 fictitious suppliers (verified IBANs with valid checksums) and 10 purchase orders.
- `POST /invoices`: upload of XML or PDF invoices with type detection from the content, size limit (`INVOICEGUARD_MAX_UPLOAD_BYTES`), content-addressed storage on a volume, SHA-256 duplicate detection (`409` with the existing id) and an audit event.
- `GET /invoices` (newest first, `limit`/`offset`) and `GET /invoices/{id}`.
- API tests against a real PostgreSQL (Compose db locally, service container in CI), including migration up/down and a models-vs-migrations check; the CI smoke test now seeds and uploads.
- E-invoice reader (`apps/api` `parsing/`, ADR-005): XRechnung UBL and CII and ZUGFeRD 2.x / Factur-X (XML embedded in
  PDF, extracted with `factur-x`) read by an own `lxml` parser into a typed model with the R1 business terms, stored
  per BT code in `invoice_fields` (line terms with `line_no`).
- Hardened XML parsing: no entity expansion, no DTD loading, no network, any DOCTYPE rejected; XXE and billion-laughs
  attack files in the tests.
- Background processing (ADR-007): `received → processing → ready / awaiting_extraction / failed` with a
  `status_reason`, an audit event per status change, idempotent steps, and startup recovery of unfinished invoices.
- Migration 0002: status `awaiting_extraction` (PDF without embedded XML, waits for LLM extraction) and
  `invoices.status_reason`.
- Several different payee IBANs on one invoice: the first is stored, a warning is logged and recorded in the audit event.
- Test samples (made-up data) for CII, UBL, ZUGFeRD 2.x PDF, ZUGFeRD 1.0, broken XML, XXE and billion laughs, and a
  differential test against `factur-x`'s own parser.
- Dependencies `factur-x`, `lxml` and `pypdf`, pinned to exact versions.
- Invoice checks (`apps/api` `checks/`): pure functions over a context loaded once from the database and the
  validator, each result stored in `checks` with status (`passed`, `warning`, `failed`, `skipped`), message and
  JSON evidence; a re-run replaces the old results.
  - `kosit`: official KoSIT validation, XRechnung 3.0.2 rules.
  - `vat_math`: lines, totals and tax per rate, Decimal, ±0.01.
  - `duplicate`: same seller and invoice number → failed; same amount and close date → warning.
  - `supplier_known`.
  - `iban`: ISO 13616 checksum, verified registry IBAN, a changed IBAN → failed; plus `no_payee_iban` and
    `multiple_payee_ibans` warnings.
  - `po_match`: order of the same supplier, totals and lines within tolerance, with the differences.
- After parsing, any failed check sets the invoice to `blocked`, otherwise `ready`. The final audit event carries a
  summary of the checks, and `status_reason` names the failed ones.
- `GET /invoices/{id}` includes the check results, worst first.
- KoSIT validator service (`services/validator`, ADR-009): official validator 1.6.3 with the XRechnung configuration
  v2026-08-31, in its HTTP daemon mode, non-root. The jar and the configuration zip are pinned by SHA-256 and the
  base images by digest. The service is in Docker Compose (`validator`, port 8081). The API calls it with a timeout
  (`INVOICEGUARD_VALIDATOR_URL`, `INVOICEGUARD_VALIDATOR_TIMEOUT_SECONDS`); when the validator is down, the KoSIT
  check is `skipped`.
- Reader: BT-13 (order reference), BT-106/BT-107/BT-108 (line total, allowances, charges) and the VAT breakdown
  (BG-23) for UBL and CII, cross-checked against `factur-x`.
- Migration 0003: `checks.message`.
- Test sample `ubl_fraud_iban.xml` (changed payee IBAN), recorded KoSIT reports, unit tests for every check, and
  end-to-end tests for `ready` and `blocked`. Tests marked `kosit` run against the real validator; CI runs them on the
  Compose service.
- The CI smoke test checks that a clean invoice ends `ready` with every check passed (KoSIT included) and that the
  fraud sample ends `blocked` with the IBAN evidence.

### Changed
- `POST /invoices/{id}/approve` approves `ready` invoices only; a blocked invoice needs the four-eyes override
  (ADR-016), and the R1 field `override_reason` is refused with `422`.
- The Playwright tests run in one worker: the spec files share one stack and the DATEV export.
- `GET /ready` checks the database and returns `503` when it is unreachable.
- The api container applies migrations on start, waits for a healthy `db` and stores uploads in the `uploads` volume.
- uvicorn starts the app through the `create_app` factory (`--factory`), so importing the module does not read settings.
- `POST /invoices` returns `202 Accepted` (was `201`) and schedules processing; invoice responses include `status_reason`.
- The CI smoke test uploads a sample XRechnung, expects `202` and polls until the invoice is `ready`.
- Processed invoices end in `ready` or `blocked` depending on the checks (before: `ready` once read).
- Tests read an invoice after upload by polling until processing has finished, as the UI does.
