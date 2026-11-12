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

## Open decisions
- Demo hosting (where the API runs: cluster or free host) and domain: decide by the end of R1.

## Next
- R1: PDF extraction via LLM for `awaiting_extraction` (then run the checks on the extracted fields), review queue,
  CSV export

## Known limitations
- Duplicate check race: two copies of the same invoice processed at the same moment can both pass, because each
  sees no other stored invoice yet. Unlikely at demo load (one API process, ADR-007); a unique index on
  (seller, normalised invoice number) or a per-seller advisory lock would close it.
- PO matching pairs invoice and order lines by position; reordered or split lines show false differences. Planned:
  match by item ID (BT-155/BT-156) or order line reference (BT-132).
- Only the first payee IBAN is compared with the registry; further ones only raise `multiple_payee_ibans`.
- The KoSIT XRechnung configuration does not validate other ZUGFeRD profiles (warning "not validated").
- An invoice processed while the validator was down keeps a `skipped` KoSIT result; there is no automatic re-run.

## Lessons learned
- Docker Compose v5 on Windows builds through Bake: run Compose from the folder that holds the compose file when build contexts are outside it.
- Generate tool baselines that store file paths (detect-secrets) on Linux, so paths use `/` and match in CI and pre-commit.
- On Windows use `127.0.0.1`, not `localhost`, in database URLs: `localhost` tries IPv6 first and stalls.
- `ADD` of a remote file in a Dockerfile stores it with mode 600: a non-root runtime user cannot read it without a chmod.
- Background work started at app startup can race with request-triggered work; tests should poll the public status
  like a client does, not assume the request's own task did the work.
- Libraries can parse untrusted input on your behalf: factur-x parses PDF attachments with lxml's defaults before our
  hardened parser sees them, so check what a dependency does with hostile input, not only what it returns.
