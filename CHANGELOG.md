# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
- `GET /ready` checks the database and returns `503` when it is unreachable.
- The api container applies migrations on start, waits for a healthy `db` and stores uploads in the `uploads` volume.
- uvicorn starts the app through the `create_app` factory (`--factory`), so importing the module does not read settings.
- `POST /invoices` returns `202 Accepted` (was `201`) and schedules processing; invoice responses include `status_reason`.
- The CI smoke test uploads a sample XRechnung, expects `202` and polls until the invoice is `ready`.
- Processed invoices end in `ready` or `blocked` depending on the checks (before: `ready` once read).
- Tests read an invoice after upload by polling until processing has finished, as the UI does.
