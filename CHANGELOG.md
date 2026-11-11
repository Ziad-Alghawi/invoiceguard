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

### Changed
- `GET /ready` checks the database and returns `503` when it is unreachable.
- The api container applies migrations on start, waits for a healthy `db` and stores uploads in the `uploads` volume.
- uvicorn starts the app through the `create_app` factory (`--factory`), so importing the module does not read settings.
