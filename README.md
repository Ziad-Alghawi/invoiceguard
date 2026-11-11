# InvoiceGuard

[![CI](https://github.com/Ziad-Alghawi/invoiceguard/actions/workflows/ci.yml/badge.svg)](https://github.com/Ziad-Alghawi/invoiceguard/actions/workflows/ci.yml)

Agentic platform for incoming supplier invoices (XRechnung, ZUGFeRD, PDF): it reads them, checks them against rules and master data, catches fraud and prompt-injection attacks, prepares the booking, and lets a human approve. The agent can never pay or post anything on its own.

> Status: R0 (foundation) done, R1 (working core) next. Sections below are filled as each release lands.

## Problem

_Coming in R1._

## Demo

_Coming in R1 (live link), GIF in R5._

## Architecture

_Coming in R5 (diagram). Monorepo layout: `apps/`, `services/`, `packages/`, `infra/`, `workflows/`, `docs/`._

## How it works

1. **Upload** (`POST /invoices`): the file is stored, the API answers `202` at once and processes it in the
   background ([ADR-007](docs/decisions/ADR-007-background-execution.md)).
2. **Read** by deterministic code, not an LLM ([ADR-002](docs/decisions/ADR-002-code-vs-llm-boundary.md),
   [ADR-005](docs/decisions/ADR-005-zugferd-xrechnung-reader.md)): XRechnung (UBL and CII) and ZUGFeRD 2.x /
   Factur-X are read into EN 16931 business terms (BT-1 invoice number, BT-84 payee IBAN, totals, lines).
   PDFs without embedded XML wait for LLM extraction (next step).
3. Checks, review queue and export follow in R1.

## Safety design

_Coming in R2 (approval gate, read-only tools, injection boundaries, OWASP Agentic Top 10 mapping)._

## Results

_Coming in R3 (field accuracy, fraud recall, attack success rate, cost per invoice, p95 latency)._

## Model comparison

_Coming in R4._

## Run locally

Requires Docker and GNU make (on Windows: `scoop install make` or `winget install ezwinports.make`).

```sh
git clone https://github.com/Ziad-Alghawi/invoiceguard.git && cd invoiceguard
cp .env.example .env
make dev        # api + web + db, applies database migrations, waits until all are healthy
make seed       # German demo suppliers, verified bank accounts and purchase orders (safe to rerun)
```

Open http://localhost:3000: the page shows `API: ok`. Upload an e-invoice (XML or PDF) to the API:

```sh
curl -F "file=@apps/api/tests/fixtures/ubl_xrechnung.xml" http://localhost:8000/invoices   # 202, 409 if already uploaded
curl http://localhost:8000/invoices/<id>                         # status: received → processing → ready
curl http://localhost:8000/invoices                              # newest first
```

The API docs are at http://localhost:8000/docs. `make down` stops the stack (data is kept in volumes).

For development without Docker you also need [uv](https://docs.astral.sh/uv/) and Node.js 24 with pnpm
(see [apps/api](apps/api/README.md) and [apps/web](apps/web/README.md)):

| Command | What it runs |
| --- | --- |
| `make check` | ruff, ruff format, mypy, eslint, tsc, prettier |
| `make test` | pytest (against a `_test` database in the running db container), vitest |
| `make eval` | evaluation harness (R3) |
| `uvx pre-commit install` | git hooks: ruff, prettier, whitespace, large files, detect-secrets |

## Decisions

Architectural choices are recorded as ADRs in [docs/decisions](docs/decisions/README.md):

- [ADR-001: Technology stack](docs/decisions/ADR-001-stack.md)
- [ADR-002: Boundary between deterministic code and LLMs](docs/decisions/ADR-002-code-vs-llm-boundary.md)
- [ADR-003: Human approval is a hard gate](docs/decisions/ADR-003-approval-hard-gate.md)
- [ADR-004: Model router with LiteLLM](docs/decisions/ADR-004-model-router.md)
- [ADR-005: Reading ZUGFeRD and XRechnung with factur-x and an own lxml parser](docs/decisions/ADR-005-zugferd-xrechnung-reader.md)
- [ADR-006: Demo authentication with seeded email/password users](docs/decisions/ADR-006-demo-auth.md)
- [ADR-007: Background execution with FastAPI BackgroundTasks and a status column](docs/decisions/ADR-007-background-execution.md)
- [ADR-008: Synchronous SQLAlchemy 2 with psycopg 3](docs/decisions/ADR-008-sync-database-access.md)

## Roadmap

- R0 Foundation: repo, tooling, CI, Docker Compose
- R1 Working core: parsing, validation, checks, review queue, CSV export, live demo
- R2 Agent, MCP servers, approval gate, injection defence
- R3 Evals, RAG booking suggestions, CI quality gate
- R4 Platform: Helm, Argo CD, observability, model router, n8n
- R5 Polish: German UI, README EN + DE, demo video

## Limitations

- ZUGFeRD 1.0 (superseded in 2019) and UBL credit notes are not read; they end in `failed` with a reason.
- Only the first payee IBAN is stored when an invoice names several; the case is flagged for the IBAN check.
- Background processing runs inside the API process (ADR-007): one API instance only, no automatic retries.

## Deutsch

_Kommt in R5._

## License

[MIT](LICENSE)
