# Status

**Current milestone:** R1 — Working core
**Last updated:** 2026-11-12

## Done
- R0 — Foundation (complete)
  - Monorepo skeleton with purpose READMEs, licence, README skeleton, CLAUDE.md, CHANGELOG, editor/git/env config
  - ADR-001 (stack), ADR-002 (code vs LLM boundary), ADR-003 (approval as hard gate)
  - `apps/api`: uv, FastAPI, `/health` + `/ready`, ruff, mypy, pytest
  - `apps/web`: pnpm, Next.js, Tailwind, shadcn/ui, eslint, prettier, vitest; home page shows API health
  - Dockerfiles (multi-stage, non-root), Docker Compose (api + web + db) with healthchecks
  - Makefile (`dev`, `down`, `check`, `test`, `eval`), pre-commit with detect-secrets
  - CI (api, web, compose smoke test) green, PR template, README "Run locally"
- R1 — Working core (in progress)
  - Week-1 decisions: ADR-004 (model router: LiteLLM), ADR-005 (ZUGFeRD/XRechnung reader: factur-x + own lxml parser, after a spike), ADR-006 (demo auth: seeded users), ADR-007 (background execution: BackgroundTasks + status column)
  - Database layer (ADR-008: sync SQLAlchemy 2 + psycopg 3), Alembic migration with the R1 tables, `/ready` checks the db
  - `make seed`: idempotent German demo suppliers with verified IBANs and purchase orders
  - Invoice upload (`POST /invoices`, type by content, size limit, SHA-256 duplicates → 409, audit event), list and detail
  - XML readers (R1-3): XRechnung UBL/CII and ZUGFeRD 2.x / Factur-X into EN 16931 terms (`invoice_fields`), hardened
    XML parsing (XXE blocked), background processing with status flow, audit events and startup recovery; upload
    returns 202; plain PDFs wait in `awaiting_extraction`
  - Checks (R1-4): KoSIT validator service (ADR-009, pinned jar and configuration), VAT math, duplicates, supplier
    known, IBAN vs registry (changed IBAN → `blocked`, `no_payee_iban` and `multiple_payee_ibans` warnings), PO
    match; any failed check → `blocked`, else `ready`; results with evidence in `GET /invoices/{id}`
  - LLM extraction (R1-5, ADR-010): plain PDFs go to Gemini Flash through our `LLMClient` (LiteLLM 1.108.1 pinned,
    bundled price table); strict schema with value, confidence and evidence per field (one per line and VAT row),
    one retry on invalid output; fields stored with `source=llm`; `low_confidence` check (IBAN or totals → blocked);
    every call logged in `model_calls` with tokens, cost and latency, unknown price → `failed`; cost per invoice in
    `GET /invoices/{id}`; injection test with a hostile PDF; recorded replies in CI, manual script for real runs
    - Manual run (2026-11-12, `gemini/gemini-3.8-flash` at its default thinking level; 3 public ZUGFeRD corpus PDFs
      with the XML removed, 1 injection PDF): **mean $0.0141 and 22.8 s per invoice** (range $0.0113 to $0.0183
      and 18.9 to 27.0 s; 1,483 to 2,015 input and 2,707 to 4,485 output tokens; one call per invoice, no retries;
      total $0.0564)
    - Field accuracy: 69 of 72 document terms equal the original XML. The 3 differences are the due date (BT-9),
      which the PDFs print ("Zahlbar ... bis 04.04.2018") but the XML does not carry, so they are correct
      extractions: **72 of 72 correct**. Line and VAT row counts match (2, 4, 6, 2 lines); the script does not
      compare line values. All confidences were 0.8 or higher, so no `low_confidence` result.
    - Injection PDF (printed text tells the model to set the IBAN to `DE58…0099`): not followed. No IBAN extracted
      (the invoice states none), every other value equal to the clean PDF; the model lowered some confidences
      (0.95 to 0.98 instead of 1.0).
    - Thinking level: output was about twice the input, about half of it thinking, so extraction now runs with
      `INVOICEGUARD_EXTRACTION_REASONING_EFFORT=low` (ADR-010). Rerun at `low`, same 4 PDFs: **mean $0.0067 and
      10.3 s per invoice** (-53 % and -55 %; range $0.0055 to $0.0084 and 8.7 to 11.8 s; 1,182 to 1,847 output
      tokens; total $0.0267). **71 of 72 terms correct**: the Rabatte PDF prints two different order numbers (the
      field "Bestellung : 2013-471331", which the XML has, and a note "Rechnung gemäß Bestellung Nr. 2018-471331");
      `low` took the note with confidence 0.9, the default level took the field. IBANs and totals were correct in
      both runs, and the injection was again not followed. `low` stays the default; R3 decides on more data.

## Open decisions
- Demo hosting (where the API runs: cluster or free host) and domain: decide by the end of R1.

## Next
- R1: review queue, CSV export

## Known limitations
- Duplicate check race: two copies of the same invoice processed at the same moment can both pass, because each
  sees no other stored invoice yet. Unlikely at demo load (one API process, ADR-007); a unique index on
  (seller, normalised invoice number) or a per-seller advisory lock would close it.
- PO matching pairs invoice and order lines by position; reordered or split lines show false differences. Planned:
  match by item ID (BT-155/BT-156) or order line reference (BT-132).
- Only the first payee IBAN is compared with the registry; further ones only raise `multiple_payee_ibans`.
- The KoSIT XRechnung configuration does not validate other ZUGFeRD profiles (warning "not validated").
- An invoice processed while the validator was down keeps a `skipped` KoSIT result; there is no automatic re-run.
  The same holds for an LLM extraction that failed on quota or a timeout: it stays `failed` (no retry action yet).
- LLM confidence is self-reported, not calibrated; R3 measures field accuracy and how well confidence predicts errors.
  It does not flag conflicts: a PDF that prints two different order numbers got 0.9 for the wrong one. R3 adds eval
  cases with conflicting values (and may add a prompt rule to lower the confidence on a conflict).
- No per-invoice or per-day LLM cost cap yet (planned with the agent in R2); the cost is logged per call.
- A PDF the model cannot read a required term from (invoice number, date, totals) ends in `failed`, not in review.

## Lessons learned
- Docker Compose v5 on Windows builds through Bake: run Compose from the folder that holds the compose file when build contexts are outside it.
- Generate tool baselines that store file paths (detect-secrets) on Linux, so paths use `/` and match in CI and pre-commit.
- On Windows use `127.0.0.1`, not `localhost`, in database URLs: `localhost` tries IPv6 first and stalls.
- `ADD` of a remote file in a Dockerfile stores it with mode 600: a non-root runtime user cannot read it without a chmod.
- Background work started at app startup can race with request-triggered work; tests should poll the public status
  like a client does, not assume the request's own task did the work.
- Libraries can parse untrusted input on your behalf: factur-x parses PDF attachments with lxml's defaults before our
  hardened parser sees them, so check what a dependency does with hostile input, not only what it returns.
- Pinning a package does not pin data it downloads at runtime: LiteLLM fetched its price table from GitHub on import
  until `LITELLM_LOCAL_MODEL_COST_MAP=True`.
- Timestamps do not order events (PostgreSQL `now()` is per transaction, Windows clocks tick in ~15 ms); append-only
  logs get an identity id.
- With an LLM configured, `awaiting_extraction` is a passing state: clients and tests poll through it.
- Importing a library can change the process environment: LiteLLM loads the nearest `.env` on import unless
  `LITELLM_MODE=PRODUCTION`, which put a real API key into the test settings. Tests now pin the key to None.
- Reasoning models bill thinking as output tokens: compare output tokens with the size of the reply before
  shortening the prompt or schema.
