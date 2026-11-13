# InvoiceGuard

[![CI](https://github.com/Ziad-Alghawi/invoiceguard/actions/workflows/ci.yml/badge.svg)](https://github.com/Ziad-Alghawi/invoiceguard/actions/workflows/ci.yml)

Agentic platform for incoming supplier invoices (XRechnung, ZUGFeRD, PDF): it reads them, checks them against rules and master data, catches fraud and prompt-injection attacks, prepares the booking, and lets a human approve. The agent can never pay or post anything on its own.

> Status: R0 (foundation) done, R1 (working core) in progress. Sections below are filled as each release lands.

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
   ([ADR-012](docs/decisions/ADR-012-review-decisions-in-r1.md)). The API enforces these rules, not the UI. Every
   login, failed login, logout, upload, status change, override and decision is written to an append-only audit
   log (a database trigger rejects changes).
5. DATEV-style CSV export follows in R1.

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
- [ADR-009: KoSIT validator as its own service, called over HTTP](docs/decisions/ADR-009-kosit-validator-service.md)
- [ADR-010: LLM extraction of plain PDF invoices](docs/decisions/ADR-010-llm-pdf-extraction.md)
- [ADR-011: Server-side sessions in an HttpOnly cookie, with a lockout](docs/decisions/ADR-011-session-cookie-auth.md)
- [ADR-012: Review decisions in R1: a status change by one reviewer, override with a reason](docs/decisions/ADR-012-review-decisions-in-r1.md)

## Roadmap

- R0 Foundation: repo, tooling, CI, Docker Compose
- R1 Working core: parsing, validation, checks, review queue, CSV export, live demo
- R2 Agent, MCP servers, approval gate, injection defence
- R3 Evals, RAG booking suggestions, CI quality gate
- R4 Platform: Helm, Argo CD, observability, model router, n8n
- R5 Polish: German UI, README EN + DE, demo video

## Limitations

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
  readable total or invoice number ends in `failed`; the Gemini free tier is for sample data only; there is no
  per-invoice or per-day cost cap yet (R2).
- Review (R1): one reviewer role; overriding a blocked invoice needs a reason from the same reviewer, not a second
  person, and approval is a status change, not yet a pause in the agent graph (both come in R2, ADR-012). Decisions
  are final. The lockout is per account, so anyone who knows a demo email can lock it for 15 minutes; there is no
  per-IP rate limit. The UI has no upload page yet (upload through the API).

## Deutsch

_Kommt in R5._

## License

[MIT](LICENSE)
