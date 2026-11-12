# apps/api
Python 3.12 FastAPI backend with the LangGraph pipeline (ingest, parse, check, propose, human approval, export); filled from R1.

## Run
The database runs in Docker (`make dev` from the repo root starts it). Outside Docker, set
`INVOICEGUARD_DATABASE_URL` (see the root `.env.example`), then:

```sh
uv sync
uv run alembic upgrade head
uv run invoiceguard-seed        # optional: German demo master data, safe to run again
uv run uvicorn --factory invoiceguard_api.main:create_app --reload
```

Logs are JSON, one object per line. OpenAPI docs: http://localhost:8000/docs.

## Endpoints
| Endpoint | What it does |
| --- | --- |
| `GET /health` | Liveness: the process is up. |
| `GET /ready` | Readiness: the database answers (`503` with `{"status": "unavailable"}` if not). |
| `POST /invoices` | Multipart upload (`file`) of an XRechnung/ZUGFeRD XML or PDF. Stores the file, creates the invoice with status `received`, writes an audit event, schedules processing and returns `202` with a `Location` header. |
| `GET /invoices` | Invoices, newest first (`limit` 1-200, default 50; `offset`). |
| `GET /invoices/{id}` | One invoice with its `status`, `status_reason` and `checks` (type, status, message, evidence; worst first), and `llm_calls` / `llm_cost_usd` (LLM calls for this invoice and their cost in USD), or `404`. Poll this after an upload while the status is `received` or `processing`, and also `awaiting_extraction` when LLM extraction is configured (then it is only a step before extraction). |

Upload rules:

- The file type is decided from the content (`%PDF-` or an XML declaration/root element), and the extension
  (`.xml` / `.pdf`) must agree; otherwise `415`. The client's content type is ignored.
- Files larger than `INVOICEGUARD_MAX_UPLOAD_BYTES` get `413`. Requests whose declared `Content-Length` is far above the
  limit are rejected before the body is read.
- The same file again (same SHA-256) gets `409` with the existing `invoice_id`, also when two uploads race.
- Files are stored content-addressed under `INVOICEGUARD_STORAGE_DIR` (`ab/<sha256>.xml`); the client's file name is
  kept for display only and never used as a path.

## Processing
After the upload, a background task ([processing.py](src/invoiceguard_api/processing.py), ADR-007) reads the file,
validates the XML with KoSIT, stores the fields and runs the checks:

```
received → processing → ready                  read and checked; no check failed (warnings are fine)
                      → blocked                at least one check failed; `status_reason` names them
                      → awaiting_extraction    PDF without embedded XML: LLM extraction follows (below); without an
                                               API key it waits here with a reason
                      → failed                 unsupported or broken file; `status_reason` says why

awaiting_extraction → processing → ready / blocked / failed     LLM extraction, then the same checks
```

- Every status change writes an `invoice.status_changed` audit event (actor `system`, `from`, `to`, `reason`). The
  final one also has a `checks` summary (count per status and the failed check types).
- Steps are safe to run twice: claiming is a conditional update, and fields and check results are replaced in the
  same transaction that sets the final status. An error anywhere rolls all of it back and ends in `failed`.
- On startup, invoices left in `processing` are reset to `received`, and all `received` invoices are processed again;
  with an API key, all `awaiting_extraction` invoices are extracted. This assumes one API process (ADR-007).

## LLM extraction
Plain PDFs (no embedded e-invoice XML) are read by an LLM, the one LLM step in R1
([ADR-010](../../docs/decisions/ADR-010-llm-pdf-extraction.md), [ADR-002](../../docs/decisions/ADR-002-code-vs-llm-boundary.md)).

- [llm/](src/invoiceguard_api/llm/): our `LLMClient` protocol; `litellm_client.py` is the only module that imports
  LiteLLM ([ADR-004](../../docs/decisions/ADR-004-model-router.md), pinned to 1.108.1, its bundled price table only).
- [extraction/](src/invoiceguard_api/extraction/): the PDF goes to the model as a file part between
  `<<<UNTRUSTED_DOCUMENT>>>` markers in the user message; the system prompt is a constant that says the document is
  data, never instructions. The reply must match a strict JSON schema (`extra="forbid"`): per term a value,
  confidence (0-1) and evidence (page, snippet); one confidence and evidence per line and per VAT row. It is
  converted into the same `ParsedInvoice` the XML readers produce. An invalid reply gets one retry with the error
  locations, then the invoice is `failed`.
- Fields are stored in `invoice_fields` with `source=llm`, `confidence` and `evidence`. The `low_confidence` check
  warns on fields below `INVOICEGUARD_EXTRACTION_CONFIDENCE_THRESHOLD` and fails (blocks) on a low-confidence payee
  IBAN or total. KoSIT is `skipped` (no XML).
- Every call is a row in `model_calls` (status `ok`, `invalid_output`, `price_unknown`, `error`; tokens, cost in USD,
  latency), committed before the checks run. A model without a known price fails the extraction.
  `GET /invoices/{id}` returns `llm_calls` and `llm_cost_usd`.
- Tests never call a model: `tests/fakes.py` replays recorded replies, and the LiteLLM adapter is tested with
  LiteLLM's `mock_response`. A prompt-injection test uploads a PDF whose text tells the model to change the IBAN.

Manual run with a real key (prints fields, confidence, evidence, cost and time per PDF; compares with
`<name>.expected.json` next to a PDF when present; stores nothing):

```sh
uv run --env-file ../../.env python scripts/extract_pdfs.py data/llm-samples/*.pdf
```

## Checks
[checks/](src/invoiceguard_api/checks/) holds one pure function per check. `context.py` loads what they need once
(supplier and verified IBANs, the referenced order, other invoices of the same seller, the KoSIT result), so the
checks themselves are unit-tested without a database or network. Each result has a `type`, a `status` (`passed`,
`warning`, `failed`, `skipped`), a one-sentence `message` and JSON `evidence` (amounts as strings).

| Type | Rule |
| --- | --- |
| `kosit` | KoSIT validator ([ADR-009](../../docs/decisions/ADR-009-kosit-validator-service.md)): accepted → `passed` (`warning` with rule warnings); rejected → `failed` with the rule codes; no matching scenario → `warning`; validator down, timed out or not configured → `skipped` with the reason |
| `vat_math` | With Decimal and a tolerance of 0.01: line amounts = BT-106; BT-106 - allowances + charges = BT-109; BT-109 + BT-110 = BT-112; per VAT rate taxable × rate = tax; tax per rate sums to BT-110 and taxable amounts to BT-109; line amounts per rate = taxable amount at that rate (not with document allowances/charges). Every broken rule is listed with expected, actual and difference |
| `duplicate` | Same seller (VAT ID, or name without one) and invoice number ignoring case and separators → `failed` with the other invoice ids; different number but same gross (±0.01) and issue date within 7 days → `warning` |
| `supplier_known` | Seller VAT ID found in `suppliers` → `passed`; missing or unknown → `warning` |
| `iban` | Payee IBAN with invalid ISO 13616 check digits → `failed`; one of the supplier's verified IBANs → `passed`; any other IBAN → `failed` (possible bank-detail fraud, evidence lists the verified IBANs); supplier unknown or without verified accounts → `warning` |
| `no_payee_iban` | Instead of `iban` when BT-84 is absent (direct debit, card): `warning`, not a mismatch |
| `multiple_payee_ibans` | In addition to `iban` when the invoice names several payee IBANs: `warning` (only the first is checked) |
| `low_confidence` | LLM-extracted invoices only: every field below the confidence threshold is listed; payee IBAN (BT-84) or a total (BT-109, BT-110, BT-112, BT-115) among them → `failed`, others only → `warning`, none → `passed` |
| `po_match` | No BT-13 or unknown order → `warning`; order of another supplier or unknown seller → `failed`; per line (paired **by position**) and in total: more than ordered (price, quantity, extra lines, other unit, currency, net total) → `failed`, less (partial delivery) → `warning`; differences listed per line |

Any `failed` result makes the invoice `blocked`; otherwise it is `ready` for review.

Known limitations: PO lines are paired by position, so reordered or split lines show false differences (planned:
match by item ID BT-155/BT-156 or order line reference BT-132). Two copies of the same invoice processed at the same
moment can both pass the duplicate check (see `docs/status.md`).

## Reading invoices
The reader in [parsing/](src/invoiceguard_api/parsing/) follows [ADR-005](../../docs/decisions/ADR-005-zugferd-xrechnung-reader.md):
`factur-x` only extracts the XML from a PDF, our own `lxml` code reads it with one XPath per business term.

| Format | Result |
| --- | --- |
| XRechnung CII, ZUGFeRD 2.x / Factur-X (XML or PDF, all profiles) | read (MINIMUM and BASIC WL have no lines) |
| XRechnung UBL 2.1 Invoice | read |
| UBL credit note | `failed`: not supported yet |
| ZUGFeRD 1.0 (superseded in 2019) | `failed`: not supported |
| Other XML, broken XML, XML with a DOCTYPE | `failed` |
| PDF without embedded e-invoice XML | LLM extraction (see above); `awaiting_extraction` without an API key |

Stored terms (`invoice_fields`, source `xml`): BT-1, BT-2, BT-3, BT-5, BT-9, BT-13, BT-27, BT-31, BT-44, BT-48,
BT-84, BT-106, BT-107, BT-108, BT-109, BT-110, BT-112, BT-115, and per line (`line_no` from 1) BT-126, BT-129, BT-130, BT-131, BT-146, BT-152,
BT-153. Absent optional terms get no row. The VAT breakdown (BG-23: BT-116 to BT-119 per rate) is read for the VAT
check but not stored as fields.

- **Payee IBAN (BT-84)** is often absent (direct debit, card payment); that is valid, not an error. If an invoice
  names several different payee IBANs, the first is stored and the `ready` audit event carries a
  `multiple_payee_ibans` warning, so the IBAN check can flag it.
- **XML safety:** the parser never expands entities, never loads a DTD, has no network access and rejects any
  document with a DOCTYPE, which blocks XXE and entity-expansion attacks. Tests prove both with attack files.
- `factur-x` and `lxml` are pinned to exact versions (supply-chain reason as in ADR-004). In tests,
  `factur-x`'s own parser cross-checks ours on every sample (differential test).

## Database
SQLAlchemy 2 (sync, typed models) with psycopg 3, see [ADR-008](../../docs/decisions/ADR-008-sync-database-access.md).
The schema is owned by Alembic migrations in [migrations/](migrations/); the models are in
[models.py](src/invoiceguard_api/models.py).

| Table | Content |
| --- | --- |
| `invoices` | Uploaded file: status (`received`, `processing`, `ready`, `awaiting_extraction`, `blocked`, `failed`) and `status_reason`, `xml`/`pdf`, file name, SHA-256 (unique), size, storage path |
| `invoice_fields` | EN 16931 business terms per invoice (code like `BT-1`, optional line number, value, source `xml`/`llm`, confidence and evidence for `llm`) |
| `suppliers`, `supplier_bank_accounts` | Supplier registry with IBANs (verified, since, verified by) |
| `purchase_orders`, `purchase_order_lines` | Orders for PO matching |
| `checks` | Check results per invoice (type, status, message, evidence as JSON); replaced on every run |
| `audit_events` | Who did what to which entity, when, with details as JSON |
| `model_calls` | One row per LLM call: invoice, purpose, model, status, tokens, cost (USD), latency, error, time ([ADR-004](../../docs/decisions/ADR-004-model-router.md)) |

Enums are stored as `VARCHAR` with a `CHECK` constraint, not as native PostgreSQL enums, so adding a value is a plain
migration. After changing a model:

```sh
uv run alembic revision --autogenerate -m "short description"   # then review the generated file
uv run alembic upgrade head
```

`make seed` / `invoiceguard-seed` upserts 5 fictitious German suppliers (fake bank code 12345678, valid IBAN and VAT
ID checksums) and 10 purchase orders. Running it again resets those rows and leaves other data alone.

## Configuration
Settings are read from environment variables prefixed with `INVOICEGUARD_` (see the root `.env.example`).
Invalid values stop the app at startup.

| Variable | Values | Default |
| --- | --- | --- |
| `INVOICEGUARD_ENV` | `dev`, `test`, `prod` | `dev` |
| `INVOICEGUARD_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |
| `INVOICEGUARD_DATABASE_URL` | `postgresql+psycopg://user:password@host:port/db` | required |
| `INVOICEGUARD_STORAGE_DIR` | directory for uploaded files | `data/uploads` (`/data/uploads` in Docker) |
| `INVOICEGUARD_MAX_UPLOAD_BYTES` | positive integer | `10485760` (10 MiB) |
| `INVOICEGUARD_VALIDATOR_URL` | KoSIT validator URL, for example `http://127.0.0.1:8081/` | unset: the KoSIT check is `skipped` |
| `INVOICEGUARD_VALIDATOR_TIMEOUT_SECONDS` | positive number | `20` |
| `INVOICEGUARD_LLM_API_KEY` | API key of the extraction model's provider (Gemini: Google AI Studio) | unset (or empty): plain PDFs stay `awaiting_extraction` |
| `INVOICEGUARD_EXTRACTION_MODEL` | LiteLLM model string with a known price | `gemini/gemini-3.8-flash` |
| `INVOICEGUARD_LLM_TIMEOUT_SECONDS` | positive number | `120` |
| `INVOICEGUARD_EXTRACTION_CONFIDENCE_THRESHOLD` | 0 to 1 | `0.8` |

An empty variable counts as unset.

## Checks
```sh
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

The tests run against a real PostgreSQL: `INVOICEGUARD_TEST_DATABASE_URL` names a database ending in `_test`, which
the tests drop, recreate and migrate on every run (`make test` reads it from the root `.env`; CI uses a service
container). The Compose `db` must be running locally. Tests marked `kosit` call the real validator at
`INVOICEGUARD_TEST_VALIDATOR_URL` and are skipped without it; all other tests use recorded reports
([tests/fixtures/kosit](tests/fixtures/kosit/)) and a local stub server. CI runs the `kosit` tests against the
Compose validator.

## Docker
The [Dockerfile](Dockerfile) installs the locked runtime dependencies with uv in a build stage and copies only the
virtual environment and the migrations into a `python:3.12-slim` image that runs as a non-root user on port 8000.
In Compose the container runs `alembic upgrade head` before starting uvicorn. The whole stack (api + web + db +
validator) starts with `make dev` from the repo root; see [infra](../../infra/README.md).
