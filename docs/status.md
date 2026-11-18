# Status

**Current milestone:** R3 — Evals, RAG, CI gate (in progress: R3-2 done, next R3-3)
**Last updated:** 2026-11-18

## Done
- R0 — Foundation (complete)
  - Monorepo skeleton with purpose READMEs, licence, README skeleton, CLAUDE.md, CHANGELOG, editor/git/env config
  - ADR-001 (stack), ADR-002 (code vs LLM boundary), ADR-003 (approval as hard gate)
  - `apps/api`: uv, FastAPI, `/health` + `/ready`, ruff, mypy, pytest
  - `apps/web`: pnpm, Next.js, Tailwind, shadcn/ui, eslint, prettier, vitest; home page shows API health
  - Dockerfiles (multi-stage, non-root), Docker Compose (api + web + db) with healthchecks
  - Makefile (`dev`, `down`, `check`, `test`, `eval`), pre-commit with detect-secrets
  - CI (api, web, compose smoke test) green, PR template, README "Run locally"
- R1 — Working core (complete)
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
  - Review UI, login and audit log (R1-6, ADR-011, ADR-012): seeded users only (`make seed-user`, password from
    env), Argon2id, server-side sessions in an HttpOnly cookie, lockout after 5 failed logins; every invoice
    endpoint needs a login; approve (blocked only with an override reason) and reject (reason required) with
    final statuses `approved` / `rejected` under a row lock; queue filter and total count, fields with
    low-confidence flags, file download; `audit_events` extended (user, status before/after, reason) and made
    append-only by a trigger, with `GET /invoices/{id}/audit`; web login, queue and detail pages (backend for
    frontend). Checked end to end on Docker Compose: seeded user logs in through the web form, approves a blocked
    invoice with an override, rejects another, audit rows written, logout ends the session
  - DATEV export and Playwright E2E (R1-7, ADR-013): `POST /exports/datev` writes approved, not yet exported invoices
    into a DATEV-style `EXTF` Buchungsstapel (format 700/13, Windows-1252, one row per invoice, accounts and tax keys
    from settings), one fiscal year per file; invoices are locked and linked to the export (migration 0006), so none
    is exported twice; the stored file can be downloaded again; audit events per export, invoice and download.
    "Export to DATEV" on the web queue. Golden-file and formatting tests. Playwright test (`make e2e`, CI job `e2e`
    on Docker Compose, XML only, no LLM): login, reject the fraud invoice with a reason, approve a clean one, export,
    check the downloaded CSV. API coverage 99.6 %
  - Public demo (R1-8, ADR-014): one Hetzner VPS with the Compose stack and a prod override behind a shared
    Caddy (`infra/edge`, one file per site, so other projects can share the server; Let's Encrypt for `invoiceguard.ziadalghawi.com`, security headers, no access log), `INVOICEGUARD_ENV=prod`
    for Secure cookies, no other host ports. Daily LLM budget (`INVOICEGUARD_LLM_DAILY_BUDGET_USD`, 0.50 on the demo).
    `make demo-reset` (demo mode only, nightly cron) reloads five sample invoices and the demo login; the login page
    shows the shared account. Step-by-step guide in `docs/deploy.md`. README with screenshots, architecture diagram,
    features and limits. Live since 2026-11-14 at https://invoiceguard.ziadalghawi.com (Hetzner CX23,
    Ubuntu 24.04, Docker 29.9, Compose v5.7; unattended upgrades, SSH keys only, no root login, Hetzner firewall).
    Checked from outside: Let's Encrypt certificate, HTTP → HTTPS 308, HSTS and headers, ports 3000/5432/8000/8081
    closed, browser login with a Secure, HttpOnly, SameSite=Lax cookie; reset gives 3 ready and 2 blocked with KoSIT
    passed on all XRechnung samples; nightly reset at 03:00 UTC
- R2 — Agent, MCP servers, approval gate (complete)
  - Processing graph (R2-2, ADR-015 updated): processing runs as a LangGraph graph per invoice (`read` / `extract` →
    `checks` → `review` → `decide`), thread ID = invoice ID, checkpointed by `PostgresSaver` (sync) in its own
    `langgraph` schema (migration 0007 calls the checkpointer's setup; strict serializer, plain JSON state). Every
    run ends paused at `review` (`interrupt()` first); approve and reject keep paths, rules and responses, take a
    `pg_advisory_xact_lock` on the invoice and resume with `Command(resume=...)`; only `decide` writes `approved` /
    `rejected` and the audit rows, in one transaction, and refuses a decision on a changed status. Graph runs take
    the same lock. A failed resume leaves the status unchanged; the retry pauses the thread at review again first.
    Startup pauses waiting invoices without a paused thread at review (the 8 dev invoices from R1 got one); the demo
    reset deletes the threads. `langgraph` 1.2.20, `langgraph-checkpoint-postgres` 3.2.0. No behaviour change: all
    existing API tests and the Playwright test pass unedited; new tests for restart during review, two simultaneous
    approvals, a failed and retried resume, a run without resume, and the graph's edges
  - Four-eyes override (R2-3, ADR-016 updated): `users.role` (`reviewer` / `approver`, existing users became reviewers)
    and the status `override_requested` (migration 0008). A blocked invoice is approved only in two steps by two
    people: any user requests an override with a reason (`POST /invoices/{id}/override`), then a different user
    with the approver role confirms (`approved`) or declines (`blocked`) it with a reason (`/override/confirm`,
    `/override/decline`); reviewers and the requester get `403`. `/approve` takes `ready` invoices only and refuses
    the R1 `override_reason` field. Each step resumes the paused thread under the advisory lock; `decide` writes
    the status and one audit row (`invoice.override_requested` / `_confirmed` / `_declined`) in one transaction,
    checks role and requester again (requester from the audit log), and routes back to `review` while the invoice
    stays in review. `make seed-user` seeds a reviewer and an approver (`INVOICEGUARD_SEED_USER_ROLE`,
    `INVOICEGUARD_SEED_APPROVER_*`); the demo login page shows both. Web: request, confirm and decline in the
    decision panel, the role in the header, an "Override requested" queue tab. Tests for 403s, one audit row per
    step, two approvers at once (one decision), a restart during `override_requested`, a lost pause restored by
    startup; new Playwright test for the whole flow (the E2E files now run one at a time)
  - `make deploy`: pulls and runs `make prod-up` on the demo server over SSH (`DEPLOY_HOST` in the local `.env`)
  - Security events and injection scan (R2-4): `security_events` table (migration 0009; type, severity, invoice, user,
    details, time; append-only by a trigger, no foreign key to invoices so a demo reset keeps the rows). Logged:
    failed logins (unknown email, wrong password, while locked), lockouts, refused role checks (`403`),
    self-approval attempts, prompt-injection hits. Heuristic scan (`injection.py`, no LLM) of the XML element text
    and attributes and the PDF text layer (first 20 pages): instruction phrases in English and German after NFKC,
    case folding and removal of invisible characters, plus invisible Unicode (zero-width, bidi controls, tags). A
    hit fails the new `prompt_injection` check (invoice `blocked`) and writes an `injection_suspected` event in the
    same transaction; no text layer = check `skipped`. No false positives on the test fixtures, the clean demo
    samples or the printed test invoice; business phrases such as "ignorieren Sie diese Mahnung" are tested as
    negatives. Poisoned demo sample 06 (a note to an AI, KoSIT-valid). `GET /security-events` and a web page
    `/security`, approvers only. New Playwright test for the poisoned upload and the security page
  - Read-only MCP servers (R2-5, ADR-017): `mcp-erp` (supplier master data, purchase orders with received
    quantities, goods receipts) and `mcp-registry` (VAT ID check digit and known supplier, IBAN checksum and owner,
    bank accounts with verification) as Compose services, MCP SDK 2.3.0, streamable HTTP, no host ports on the demo.
    Small typed tools, patterns on every input, fixed SQL, `READ ONLY` transactions. Migration 0010: goods receipts,
    `suppliers.contact_email`, one role per server with `SELECT` on its own tables only (registry: four supplier
    columns); `invoiceguard-db-roles` sets the passwords from the environment at api start. Tests prove that each
    role reads only its tables and columns and can neither write nor create; the servers' tests run as the roles.
    `get_invoice_history` moved to R3 (it would need access to `invoices`)
  - Exception agent (R2-6, ADR-018): own bounded loop over `LLMClient` outside the processing graph (no lock, no
    reference to the graph): one schema-validated JSON action per step (up to 3 calls of the 7 allow-listed read-only
    MCP tools, or finish), limits 8 steps / 12 tool calls / 90 s / $0.05 per invoice across runs, daily budget
    checked first. Runs automatically after processing ends `blocked` (with a model key and the MCP URLs) and on
    "Investigate"; injection-flagged invoices are refused. English finding and German email draft; recipient from
    the supplier master data. Every model and tool call saved (`agent_runs`, `agent_steps`, migration 0011; costs in
    `model_calls`) and shown on the invoice page. Without a key: recorded real runs for samples 02 and 03, labelled.
    Tests with a fake model: stops at every limit, refuses non-allow-listed actions (`approve_invoice`, ...), leaves
    status, audit log and paused thread unchanged, skips injected invoices; Playwright test in both modes
    - Real runs (2026-11-18, `gemini/gemini-3.8-flash`, reasoning `low`, local stack with the real MCP servers):
      **sample 02 (changed IBAN): $0.0060, 12.1 s**, 3 model calls, 4 tool calls (`check_iban`, `get_bank_accounts`,
      `get_purchase_order`, `get_supplier`), 5,216 in / 559 out tokens; finding: IBAN registered to no supplier, the
      verified account since 2025-01-10, confirm by phone via master-data contact; email asks for confirmation or a
      corrected invoice without quoting our bank data. **Sample 03 (price above order): $0.0044, 10.2 s**, 2 model
      calls, 2 tool calls (`get_purchase_order`, `get_goods_receipts`); finding: 380.00 invoiced vs 320.00 ordered,
      delivery WE-2026-0003 received; email asks for a corrected invoice or credit note
    - Two problems found by the real runs and fixed (journal): the case file sent unbounded check evidence (a
      duplicate warning listing ~100 invoice IDs on the dev database: 8.4k input tokens per call, $0.029 for a
      failed run), now capped per check; and Gemini left out optional schema fields, so `finish` came back without
      the email twice. Every field of the action is now required (nullable)
  - Upload page (R2-7, ADR-014 updated): `/upload` for reviewers and approvers. The browser sends the file with
    `XMLHttpRequest` (upload progress) to a route handler, which passes it to `POST /invoices` with the session (not
    behind `proxy.ts`, whose body buffering has its own size limit); then the page polls the status and links to the
    invoice. Messages for wrong type (`415`), too large (`413`), duplicate (`409`, link to the existing invoice), demo
    PDF without XML (`422`) and the hourly limit (`429`). Demo mode refuses PDFs without embedded XML at upload,
    nothing stored; `INVOICEGUARD_UPLOAD_MAX_PER_HOUR` (default 30 on the demo) counts uploads per user from the audit
    log. Tests for XML and ZUGFeRD on the demo, plain and unreadable PDFs, the limit per user and hour; Playwright test
    uploads an XML on the page and finds it in the queue
  - Reopening rejected invoices (R2-7, ADR-016 updated): `POST /invoices/{id}/reopen` with a required reason, any
    role; `approved` → `409` (it may be exported), other statuses but `rejected` → `409`. Resumes the thread under the
    advisory lock (a finished thread first pauses at review again); `decide` writes `rejected → processing`, one
    `invoice.reopened` row, and clears the old fields and checks in one transaction, then routes to `read` (new edge),
    so KoSIT and every check run again on the current master data and the thread pauses at review. Plain PDFs are
    extracted again afterwards (key and budget), blocked results investigated as after an upload. Web: "Reopen" form
    on rejected invoices; the history shows the reopen. Tests: one audit row, fresh checks after a changed IBAN in the
    registry (ready → blocked), `409` for approved, `422` without a reason, two reopens at once (one `200`, one `409`,
    three runs), decide refuses a reopen without the endpoint; Playwright test rejects and reopens an invoice
  - R2 done-when met: the poisoned sample is caught and shown (R2-4), the agent explains an exception with evidence
    (R2-6), every approval resumes the paused graph (R2-2, R2-3); all R1 and R2 Playwright tests pass

- R3 — Evals, RAG, CI gate (in progress)
  - Eval harness (R3-2, ADR-019): `packages/evals` with `invoiceguard-eval fetch / generate / run / report` and
    `make eval` (replay, free and offline). Datasets: the KoSIT testsuite (72 files) and 12 FeRD EN 16931 PDFs
    from the ZUGFeRD corpus, pinned by commit and SHA-256 in `sources.json` and downloaded into an ignored cache;
    17 generated German invoices (reportlab, byte-identical, with UBL twins and truth JSON): clean, variants
    (two rates, discount, two pages), 4 conflicting printed values, 5 fraud types. A recording `LLMClient`
    (replay by default, `--live` under a spend cap, the key covers prompt, schema, effort, file hash and run).
    The fraud set runs through the real app (`POST /invoices`) on a throwaway database, as XML and as PDF. CI job
    `evals`; 93 tests, 97 % coverage
  - Baseline (`docs/results.md`, `gemini/gemini-3.8-flash`, 29 PDFs × 3 levels × 2 runs, live spend $1.67 of the
    $3 cap): at `low` **99.2 % of document terms and 98.3 % of documents right** on completed extractions,
    98.8 % of line terms, $0.0058 and p50 9.3 s / p95 23.4 s per invoice; `medium` and `high` read the same
    (99.4 %, 99.6 %) at 2.2× and 3.8× the cost and timed out at 120 s (2 and 4 times), so **`low` stays the
    default** (ADR-010 updated). The Google project's spend cap stopped the second `high` repeat (27 of 29
    failed with `PERMISSION_DENIED`). Conflicting printed values: the right value in all 10 cases, but the
    confidence never dropped. Fraud set: **10 of 10 as expected as XML and as PDF** (KoSIT on), no clean invoice
    flagged. Parser: 72 of 72 KoSIT files read; the 9 differing UBL/CII pairs are differences in the testsuite
    files
  - Confidence measured: at `low` 8 of 9 wrong fields had 0.8 or more (AUROC 0.82); the errors cluster at
    0.8 to 0.9 (4 of 6 wrong there, 3 of 1,110 wrong at 1.0). Not fixed in R3-2: the planned evidence check would
    not catch any of the observed errors (every wrong value is printed on the page); a threshold change follows

## Open decisions
- None for R1. Demo hosting and domain settled in ADR-014.

## Next
- R3-2 follow-ups (decided 2026-11-18): `vat_math` for VAT category O (KoSIT 01.04a) is fixed; the
  `low_confidence` threshold 0.8 → 0.9 follows (on the eval set it flags 4 more of 9 errors and 2 right fields)
- R3 — Evals, RAG, CI gate (PLAN.md §11), three rounds, one PR each:
  - R3-2 Eval harness and extraction results (ADR-019): `packages/evals` with the KoSIT set, the ZUGFeRD corpus
    (pinned downloads with SHA-256, not committed), a reportlab generator with conflicting printed values, the
    fraud set; eval CLI with recorded replies and a spend cap ($3 for this round); `docs/results.md`; the
    extraction thinking level chosen on the eval set (ADR-010); confidence measured against errors, and fixed in
    code if it misleads
  - R3-3 Attack set (≥ 40 cases) and the CI gate (PR paths and nightly, baseline, a deliberate regression that
    fails); the LLM injection classifier only if the attack set shows the heuristics miss attacks
  - R3-4 RAG: pgvector booking suggestions and rulebook search with evidence in the UI, top-1/top-3 eval; agent
    tools `get_invoice_history` with `search_similar_invoices`, and `search_rulebook`
- Backlog: scan-like generated PDFs (image noise, no text layer) for the eval set

## Known limitations
- Exception agent (ADR-018): the cost cap is checked before each call, so the last call can overshoot it; the
  transcript is sent again each step (input grows with the steps); the model sees the tool contracts from the prompt,
  not their JSON schemas; findings are not evaluated yet (R3). Recorded demo runs go stale if the seed changes.
  Starting a live run is open to any logged-in user (no rate limit beyond the cost cap and the daily budget).
- MCP servers (ADR-017): no authentication between the api and the servers (reachable only inside the stack); one
  database connection per tool call; the migration needs a user that may create roles. `get_invoice_history` and
  the RAG tools come in R3.
- Review (ADR-016): approvals are final; a rejected invoice can be reopened, which runs the checks (and for a plain
  PDF the LLM extraction) again, so a reopen costs what the first run cost. On the public demo one visitor can use
  both the reviewer and the approver account, so four eyes there shows the mechanism, not real separation of duties.
  Roles are set by `make seed-user`; there is no user administration.
- Graph (ADR-015): startup reads the thread of every invoice waiting for review (one query each); each graph run
  opens its own database connection for the checkpointer; a decision waits while a run (an LLM extraction) holds
  the invoice's lock.
- Injection scan (R2-4): heuristics only, so new wordings or other languages get through (R3's attack set measures
  this; an LLM classifier only if it is needed, ADR-002). It cannot see text drawn white or tiny, text in images
  (scans without a text layer are `skipped`), or invisible PDF text (render mode 3, skipped on purpose: OCR'd scans
  use it). The security log has no alerting or retention yet.
- Login lockout is per account: anyone who knows a demo email can lock it for 15 minutes, and the `429` reveals that
  the account exists. No per-IP rate limit (ingress in R4).
- The audit trigger stops UPDATE and DELETE through the app's database user, not the table owner (TRUNCATE, dropping
  the trigger); production needs a separate, restricted database role.
- Upload limit (R2-7): counted from the audit log without a lock, so parallel uploads can pass it by a few files; the
  demo accounts are shared, so on the demo it caps all visitors together. One file per upload (no bulk upload);
  there is no sample picker: visitors bring their own XRechnung or ZUGFeRD file.
- Demo (ADR-014): one VPS, no backups (sample data, reset nightly); the shared demo login can be locked for 15 minutes
  by anyone, the nightly reset unlocks it.
- Duplicate check race: two copies of the same invoice processed at the same moment can both pass, because each
  sees no other stored invoice yet. Unlikely at demo load (one API process, ADR-007); a unique index on
  (seller, normalised invoice number) or a per-seller advisory lock would close it.
- PO matching pairs invoice and order lines by position; reordered or split lines show false differences. Planned:
  match by item ID (BT-155/BT-156) or order line reference (BT-132).
- Only the first payee IBAN is compared with the registry; further ones only raise `multiple_payee_ibans`.
- The KoSIT XRechnung configuration does not validate other ZUGFeRD profiles (warning "not validated").
- An invoice processed while the validator was down keeps a `skipped` KoSIT result; there is no automatic re-run.
  The same holds for an LLM extraction that failed on quota or a timeout: it stays `failed` (no retry action yet).
- LLM confidence is self-reported, not calibrated. Measured in R3-2: at `low` 8 of 9 wrong fields had 0.8 or
  more, so the `low_confidence` check (below 0.8) caught none of them; on the 10 conflicting-value cases the model
  picked the right value but never lowered its confidence.
- Eval (ADR-019): generated layouts are cleaner than real invoices, the corpus has 12 PDFs, the fraud set uses
  the demo seed only; scan-like PDFs are in the backlog. Calls that failed live are not recorded, so a replay of
  such a run needs `--missing-as-failed`.
- The daily LLM budget is checked before each extraction, so parallel extractions can overshoot it by one invoice
  each; PDFs it held back wait until the API restarts (no scheduler). No per-invoice cap yet (R2).
- A PDF the model cannot read a required term from (invoice number, date, totals) ends in `failed`, not in review.
- DATEV export (ADR-013): not certified and not yet imported into a real DATEV installation; one row per invoice, so
  several VAT rates (or a line without a rate) mean no BU key; one collective creditor and one expense account until
  creditor numbers and booking suggestions (R3); no exchange rate for non-EUR invoices; disallowed characters in the
  invoice number become `-` in Belegfeld 1. Storing BG-23 (VAT breakdown) would allow one row per rate.

## Lessons learned
- Check every eval "error" against the document first: 5 corpus PDFs print terms their XML leaves out, and two
  unit codes mean the same piece. Write each truth correction down with the printed text as its note.
- Run the checks on the official conformance set, not only the parser: the first eval run found a check that
  blocked a valid invoice (VAT category O, fixed after the baseline).
- Separate "the call failed" from "the answer was wrong" in every metric: a provider spend cap cut a whole run
  short, and counting those failures as wrong fields would have ranked the levels by billing, not by reading.
- PostgreSQL roles belong to the server, not the database: create them idempotently, keep passwords out of
  migrations, and test privileges with `SET ROLE` instead of logging in.
- Structured output is not "all fields": models leave out optional schema fields. Make every field required
  (nullable) when the next step needs all of them.
- Everything a loop sends to a model is sent again each step: bound data that grows with the database (check
  evidence) before it reaches a prompt.
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
- With partial prerendering, a redirect inside a Suspense boundary arrives after the 200 status and the static shell:
  guard protected pages in `proxy.ts` too, so a missing login gets a real redirect.
- Check how new a dependency release is before locking it: a transitive package published that same day can be
  pinned to the previous release until it has settled (uv `constraint-dependencies`).
- Docker publishes ports past `ufw`: firewall a Docker host outside the VM (cloud firewall) or publish nothing but
  the proxy.
- A JVM sizes its heap from the container's memory limit; without one it sees the whole server.
- A test that pins the exact set of tables turns "add a library's tables" into a design decision: an own schema
  for the checkpointer kept the application schema exact and makes its data easy to find, back up or drop.
- A resume is only a resume while the thread is paused: after a failed step the thread is past the pause, and
  `Command(resume=...)` silently does nothing. Check the pause before resuming.
- Tools can write characters you cannot see: test strings with zero-width or bidi characters ended up as literal
  characters in the source (a "Trojan Source" risk). Keep them as `\u` escapes and check new files for non-ASCII.
- A paused workflow must pause again after every decision that leaves the item in review (a declined override
  is `blocked` again): a status the UI can act on needs a thread waiting for it.
- Playwright runs spec files in parallel workers by default; end-to-end tests that share one stack and a global
  action (the DATEV export takes every approved invoice) need `workers: 1`.
- End-to-end tests against a long-lived stack must set their own preconditions: the first local E2E run exported
  2018 sample invoices, because a DATEV file holds one fiscal year and the oldest goes first.
