# InvoiceGuard

[![CI](https://github.com/Ziad-Alghawi/invoiceguard/actions/workflows/ci.yml/badge.svg)](https://github.com/Ziad-Alghawi/invoiceguard/actions/workflows/ci.yml)
![API coverage ≥ 90 %](https://img.shields.io/badge/api%20coverage-%E2%89%A590%25-brightgreen)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![Next.js](https://img.shields.io/badge/Next.js-App%20Router-black)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

InvoiceGuard checks incoming supplier invoices for German SMEs before anyone pays them. It reads XRechnung,
ZUGFeRD and plain PDF invoices, checks them against master data (verified bank accounts, purchase orders,
duplicates, VAT math, the official KoSIT validator) and blocks suspicious ones, such as a changed IBAN. A
human reviewer approves or rejects every invoice with an audit trail and exports approved ones as a DATEV-style
booking file. Nothing is ever paid or posted automatically.

> Status: R0 (foundation) and R1 (working core with a live demo) are done. R2 adds the agent and approval gate.

## Demo

**https://invoiceguard.ziadalghawi.com**: the login page shows the shared demo account. Five made-up sample
invoices are loaded and reset every night: two ready, one with a changed bank account (possible fraud), one
charging more than its purchase order, and one from an unknown supplier. Try approving the blocked ones: the
system asks for a written override reason and records it.

| Review queue | Blocked invoice: changed IBAN |
| --- | --- |
| ![Review queue with ready and blocked invoices](docs/images/queue.png) | ![Invoice detail with a failed IBAN check, evidence, decision panel and audit history](docs/images/blocked-iban.png) |

## Features

- **E-invoice reading by code:** XRechnung (UBL and CII) and ZUGFeRD 2.x / Factur-X into EN 16931 terms, with
  hardened XML parsing (XXE and entity expansion blocked).
- **LLM only where code cannot read:** plain PDFs are extracted by Gemini Flash into a strict schema with
  confidence and evidence per field; the document is untrusted data, never instructions. Every call is logged
  with tokens, cost and latency, and a daily budget caps spending.
- **Deterministic checks with evidence:** official KoSIT validator, VAT math, duplicates, known supplier, payee
  IBAN against verified accounts, purchase order match, low LLM confidence. Any failed check blocks the invoice.
- **Human review as a hard gate:** seeded logins (Argon2id, server-side sessions, HttpOnly Secure cookies,
  lockout), approve or reject with reasons, override of blocked invoices only with a written reason.
- **Append-only audit log:** every login, upload, status change and decision; a database trigger rejects edits.
- **DATEV-style export:** approved invoices as an `EXTF` Buchungsstapel CSV, each invoice exported once.
- **Built like production:** typed Python and TypeScript, 99 % API test coverage, Playwright E2E test, CI on
  every PR, Docker Compose, deployed behind Caddy with HTTPS.

## Architecture

```mermaid
flowchart LR
    reviewer([Reviewer<br/>browser]) -- HTTPS --> caddy[Caddy<br/>TLS, headers]
    caddy --> web["web: Next.js App Router<br/>review UI, backend for frontend"]
    web -- "REST + session cookie" --> api["api: FastAPI<br/>upload, processing, review, export"]
    api --> db[("PostgreSQL 16 + pgvector<br/>invoices, checks, audit log, model calls")]
    api --> files[("uploads volume")]
    api -- "XML" --> kosit["KoSIT validator<br/>(Java service)"]
    api -. "plain PDFs only,<br/>strict schema, cost cap" .-> llm[("Gemini Flash<br/>via LiteLLM")]
    api -- "approved invoices" --> datev[/"DATEV-style CSV"/]
```

Upload answers `202` and processing runs in the background: read (XML parser or LLM) → checks → `ready` or
`blocked` → human decision → export. The browser never talks to the API directly; the web server calls it with
the user's session. The public demo runs this stack on one VPS with Docker Compose
([ADR-014](docs/decisions/ADR-014-demo-hosting-single-vps.md), [deploy guide](docs/deploy.md)).

## Tech stack

| Area | Tools |
| --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (psycopg 3), Alembic, lxml, factur-x, LiteLLM, Argon2 |
| Frontend | Next.js (App Router, TypeScript), Tailwind CSS, shadcn/ui |
| Data | PostgreSQL 16 with pgvector |
| Validation | KoSIT validator with the XRechnung configuration |
| Quality | ruff, mypy (strict), pytest, ESLint, Prettier, Vitest, Playwright, pre-commit with detect-secrets |
| Delivery | Docker (multi-stage, non-root), Docker Compose, GitHub Actions, Caddy, Hetzner Cloud |
| Workflow | LangGraph with the PostgreSQL checkpointer; approval is an `interrupt()` |
| Planned | MCP servers, Langfuse, Helm, Argo CD (R2 to R4) |

## How it works

1. **Upload** (`POST /invoices`): the file is stored, the API answers `202` at once and processes it in the
   background ([ADR-007](docs/decisions/ADR-007-background-execution.md)).
2. **Read** by deterministic code, not an LLM ([ADR-002](docs/decisions/ADR-002-code-vs-llm-boundary.md),
   [ADR-005](docs/decisions/ADR-005-zugferd-xrechnung-reader.md)): XRechnung (UBL and CII) and ZUGFeRD 2.x /
   Factur-X are read into EN 16931 business terms (BT-1 invoice number, BT-84 payee IBAN, totals, lines).
   **PDFs without embedded XML** are the one place an LLM reads ([ADR-010](docs/decisions/ADR-010-llm-pdf-extraction.md)):
   Gemini Flash gets the PDF and must answer in a strict schema, with a confidence and evidence (page and printed
   text) per field. The PDF is treated as untrusted data, and the result goes through the same checks. Every model
   call is logged with tokens, cost and latency; `GET /invoices/{id}` shows the cost per invoice.
3. **Check** with deterministic rules, each stored with a status (`passed`, `warning`, `failed`, `skipped`), a message
   and its evidence:

   | Check | Fails (blocks) when | Warns when |
   | --- | --- | --- |
   | `kosit`: official KoSIT validator, XRechnung 3.0.2 ([ADR-009](docs/decisions/ADR-009-kosit-validator-service.md)) | the validator rejects the XML (rule codes as evidence) | no XRechnung scenario fits (for example ZUGFeRD BASIC); `skipped` if the validator is down |
   | `vat_math` | lines, net, tax per rate and gross do not add up (±0.01) | |
   | `duplicate` | same seller and invoice number as a stored invoice | same seller, same gross amount, issue date within 7 days |
   | `supplier_known` | | the seller VAT ID is not in the supplier master data |
   | `iban` | invalid IBAN, or not one of the supplier's verified IBANs (possible fraud) | supplier unknown; `no_payee_iban` (direct debit) and `multiple_payee_ibans` are separate warnings |
   | `po_match` | order of another supplier; more charged than ordered (total, price, quantity, extra lines) | no or unknown order reference; less charged (partial delivery) |
   | `low_confidence` (LLM-extracted only) | the payee IBAN or a total was extracted below the confidence threshold | any other field below the threshold |

   Any failed check ends in **`blocked`**, otherwise **`ready`** for review. `GET /invoices/{id}` returns the results,
   worst first.
4. **Review** in the web app: a seeded reviewer logs in ([ADR-011](docs/decisions/ADR-011-session-cookie-auth.md)),
   works through the queue and opens an invoice: check results with evidence, extracted fields (low-confidence LLM
   fields highlighted with the printed text), the original file and the audit history. A **`ready`** invoice can be
   approved; a **`blocked`** one only with a written override reason; any of them can be rejected with a reason
   ([ADR-012](docs/decisions/ADR-012-review-decisions-in-r1.md)). The API enforces these rules, not the UI. Each
   invoice is a LangGraph thread that pauses at review with `interrupt()`; a decision resumes it, and only the
   graph's last step writes `approved` or `rejected`
   ([ADR-015](docs/decisions/ADR-015-processing-graph-approval-interrupt.md)). Every
   login, failed login, logout, upload, status change, override and decision is written to an append-only audit
   log (a database trigger rejects changes).
5. **Export** approved invoices to accounting with **Export to DATEV** on the queue
   ([ADR-013](docs/decisions/ADR-013-datev-style-export.md)): a DATEV-style booking file ("Buchungsstapel", `EXTF`
   format 700/13, Windows-1252, `;`, decimal comma) with one row per invoice: gross amount, creditor and expense
   account, BU tax key, document date, invoice number (Belegfeld 1) and supplier name. Accounts, advisor and client
   number and the tax keys are settings (`INVOICEGUARD_DATEV_*` in `.env`). An invoice goes into one file only; the
   file is stored and can be downloaded again, and every export and download is audited. This is **not a certified
   DATEV interface**: it follows DATEV's public format description and needs a check by the tax advisor's first
   import.

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
# Edit .env: set INVOICEGUARD_SEED_USER_PASSWORD (at least 12 characters, no $ or #) and, if you like, the
# email and name of the reviewer. Never commit .env.
make dev        # api + web + db + KoSIT validator, applies migrations, waits until all are healthy
make seed       # German demo suppliers, verified bank accounts and purchase orders (safe to rerun)
make seed-user  # creates the reviewer from INVOICEGUARD_SEED_USER_* (rerun to reset the password or unlock)
```

There is no sign-up: to add another reviewer, change the three `INVOICEGUARD_SEED_USER_*` values and run
`make seed-user` again. Five wrong passwords in a row lock an account for 15 minutes; `make seed-user` unlocks it.

Open http://localhost:3000: the page shows `API: ok`. The API needs a login, so log in with curl and keep the
session cookie, then upload e-invoices (XML or PDF):

```sh
curl -c cookies.txt -H "Content-Type: application/json" \
  -d '{"email": "reviewer@example.com", "password": "<your password>"}' http://localhost:8000/auth/login
curl -b cookies.txt -F "file=@apps/api/tests/fixtures/ubl_xrechnung.xml" http://localhost:8000/invoices   # 202
curl -b cookies.txt -F "file=@apps/api/tests/fixtures/ubl_fraud_iban.xml" http://localhost:8000/invoices  # → blocked
```

Then open http://localhost:3000/invoices, log in with the same account, and approve or reject them. The changed-IBAN
invoice is `blocked`: approving it needs an override reason. Each invoice page shows its audit history.

Click **Export to DATEV** on the queue to download the approved invoices as `EXTF_Buchungsstapel_<time>.csv`. It
opens in Excel or LibreOffice (separator `;`, encoding Windows-1252) and imports into DATEV as a Buchungsstapel.
The same file is also available through the API: `curl -b cookies.txt -X POST http://localhost:8000/exports/datev`
returns its `file_url`.

To extract plain PDFs, put a Gemini API key (Google AI Studio) into `INVOICEGUARD_LLM_API_KEY` in `.env` and run
`make dev` again. Without a key, plain PDFs wait in `awaiting_extraction`. The free tier may use what you send to
improve Google's models: send only made-up or public sample invoices.

The API docs are at http://localhost:8000/docs. `make down` stops the stack (data is kept in volumes).

For development without Docker you also need [uv](https://docs.astral.sh/uv/) and Node.js 24 with pnpm
(see [apps/api](apps/api/README.md) and [apps/web](apps/web/README.md)):

| Command | What it runs |
| --- | --- |
| `make check` | ruff, ruff format, mypy, eslint, tsc, prettier |
| `make test` | pytest (against a `_test` database and the validator in the running stack), vitest |
| `make e2e` | Playwright browser test against the running stack (after `make seed` and `make seed-user`) |
| `make eval` | evaluation harness (R3) |
| `make prod-up`, `make demo-reset` | the public demo stack behind Caddy, and its nightly reset ([deploy guide](docs/deploy.md)) |
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
- [ADR-009: KoSIT validator as its own service, called over HTTP](docs/decisions/ADR-009-kosit-validator-service.md)
- [ADR-010: LLM extraction of plain PDF invoices](docs/decisions/ADR-010-llm-pdf-extraction.md)
- [ADR-011: Server-side sessions in an HttpOnly cookie, with a lockout](docs/decisions/ADR-011-session-cookie-auth.md)
- [ADR-012: Review decisions in R1: a status change by one reviewer, override with a reason](docs/decisions/ADR-012-review-decisions-in-r1.md)
- [ADR-013: DATEV-style booking export (EXTF Buchungsstapel), one row per invoice](docs/decisions/ADR-013-datev-style-export.md)
- [ADR-014: R1 demo on one VPS with Docker Compose and Caddy](docs/decisions/ADR-014-demo-hosting-single-vps.md)
- [ADR-015: Processing graph with LangGraph, approval as `interrupt()`](docs/decisions/ADR-015-processing-graph-approval-interrupt.md)
- [ADR-016: Four-eyes override of blocked invoices and reopening rejected invoices](docs/decisions/ADR-016-four-eyes-override-and-reopen.md)

## Roadmap

- R0 Foundation: repo, tooling, CI, Docker Compose
- R1 Working core: parsing, validation, checks, review queue, CSV export, live demo
- R2 Agent, MCP servers, approval gate, injection defence
- R3 Evals, RAG booking suggestions, CI quality gate
- R4 Platform: Helm, Argo CD, observability, model router, n8n
- R5 Polish: German UI, README EN + DE, demo video

## Limitations

- **Demo, not a product:** the public demo holds made-up sample data only and is reset every night. Do not
  upload real invoices. Its login is shared and shown on the login page, so anyone can lock it for 15 minutes
  with wrong passwords. One small server, no backups, no SLA.
- **Not a certified DATEV interface** (details below), and no connection to an ERP or bank: InvoiceGuard
  prepares a decision and a booking file, it never pays or posts.
- ZUGFeRD 1.0 (superseded in 2019) and UBL credit notes are not read; they end in `failed` with a reason.
- Only the first payee IBAN is stored and checked when an invoice names several; the others are flagged as a
  `multiple_payee_ibans` warning, not compared with the registry.
- PO matching pairs invoice lines with order lines **by position** (first with first). A supplier who reorders or
  splits lines gets false differences. Matching by item ID (BT-155/BT-156) or the order line reference (BT-132) is
  the planned fix.
- The duplicate check can miss a duplicate when two copies are processed at the same moment (each sees no other
  stored invoice yet). Unlikely at demo load; a unique constraint or a lock per seller would close it.
- The KoSIT configuration covers XRechnung and plain EN 16931; other ZUGFeRD profiles get a "not validated" warning.
- Background processing runs inside the API process (ADR-007): one API instance only, no automatic retries
  (an invoice checked while the validator was down keeps its `skipped` KoSIT result, and an extraction that hit the
  LLM quota stays `failed`).
- LLM extraction: the model's confidence is self-reported, not calibrated (R3 measures it); a PDF without a
  readable total or invoice number ends in `failed`; the Gemini free tier is for sample data only; there is a per-day cost cap
  (`INVOICEGUARD_LLM_DAILY_BUDGET_USD`) but no per-invoice cap yet (R2), and PDFs held back by the cap are only
  picked up again when the API restarts.
- Review (R1): one reviewer role; overriding a blocked invoice needs a reason from the same reviewer, not a second
  person (four-eyes override comes in R2, ADR-016). Decisions
  are final. The lockout is per account, so anyone who knows a demo email can lock it for 15 minutes; there is no
  per-IP rate limit. The UI has no upload page yet (upload through the API).
- DATEV export: not certified and not yet imported into a real DATEV installation. One row per invoice, so invoices
  with several VAT rates (or lines without a rate) get no tax key and the advisor sets the tax; one collective
  creditor and one expense account for all invoices until booking suggestions (R3); no exchange rate for non-EUR
  invoices; invoice numbers lose characters DATEV does not allow in Belegfeld 1 (they become `-`).

## Deutsch

_Kommt in R5._

## License

[MIT](LICENSE)
