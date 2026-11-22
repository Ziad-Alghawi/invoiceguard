# Status

**Current milestone:** R5 — Polish and story (R4 complete; R5-1 merged; R5-3 German UI in review)
**Last updated:** 2026-11-22

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

- R3 — Evals, RAG, CI gate (complete)
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
  - Follow-ups done (2026-11-18): `vat_math` accepts VAT category O (KoSIT 01.04a); the `low_confidence` default is
    0.9 (replay at `low`: wrong fields flagged 1 → 5 of 9, right fields flagged 2 → 4 of 1,197; fraud-set numbers
    in `docs/results.md` carried over from commit `c94c320`, not rerun)
  - Confidence measured: at `low` 8 of 9 wrong fields had 0.8 or more (AUROC 0.82); the errors cluster at
    0.8 to 0.9 (4 of 6 wrong there, 3 of 1,110 wrong at 1.0). Not fixed in R3-2: the planned evidence check would
    not catch any of the observed errors (every wrong value is printed on the page); a threshold change follows
  - Attack set and CI gate (R3-3, ADR-019 updated): 44 poisoned twins of generated invoices (PDF visible, white
    and 1 pt text, seller and item names, XML notes, filenames; change IBAN or totals, approve, skip checks,
    reveal the prompt, call tools; en, de, fr, tr), run through the app on the eval database and, when blocked,
    through the real exception agent with the real MCP servers in process. One live run (103 calls, $0.31 of the
    $0.90 cap), replayed: **0 of 44 attacks succeeded end to end and 0 model only** (agent run on scan-flagged
    invoices too); the heuristic scan flagged **14 of 44** (none of the 24 indirect wordings, filenames, French
    or Turkish), regexes not tuned to the set. No LLM injection classifier: no attack got through. The fraud set
    rerun on the eval database at threshold 0.9: 10 of 10 as XML and as PDF, no clean invoice flagged. CI
    workflow `eval-gate` (replay, no key; `small` on PRs touching prompts, agent, checks, parsers, MCP servers or
    the evals, `full` nightly; KoSIT validator built in the job) fails on a field-accuracy drop over 2 points,
    any successful attack, a smaller attack set, or cost per invoice up more than 25 % against
    `packages/evals/baselines/`; `make eval-gate` locally. promptfoo not used (ADR-019)
  - Booking suggestions (R3-4a, ADR-020): pgvector in our PostgreSQL (migration 0012: `embeddings` one vector per
    text and model, `bookings` one row per booked line; extensions `vector` and `pg_trgm`, `pgvector` 0.5.1 for the
    SQLAlchemy type). `LLMClient` gained `Embedder.embed`: `gemini/gemini-embedding-001`, 768 dimensions, task
    `SEMANTIC_SIMILARITY` (checked with one live call before coding). After processing (upload, reopen) a
    background task embeds the new line texts within the daily budget, logged in `model_calls`; a failure changes
    nothing on the invoice. `GET /invoices/{id}/bookings`: the 10 nearest searchable bookings by cosine (or by
    trigram text match for a line without a vector), +0.1 for the same supplier, a vote that weighs each neighbour
    by exp((score - best) / 0.05), top 3 accounts with their sources; an invoice is never its own evidence; no
    chat model. `/approve` and `/override/confirm` take an account per line (all or none, from a short SKR03
    list), written by the decide node with the top suggestion and the user, listed in the audit row; an
    injection-flagged invoice's bookings are `searchable = false`. Web: one account dropdown per line in the
    approve and confirm forms, preselected with the suggestion and its evidence. `make index` /
    `invoiceguard-index` imports the generated booking history (10 suppliers, 79 invoices, 159 lines) and packaged
    vectors (history and demo sample lines), then embeds what is missing with a key; the demo reset imports both.
    Eval part `bookings` (62 held-out lines): **98.4 % top-1 / 100 % top-3 by vector**, hit@1 98.4 %, MRR 0.984;
    text match 91.9 % / 100 % (held-out wordings 82.1 %); the supplier's most frequent account 45.2 %. The first
    vote (plain sum of similarities) scored 95.2 % and was replaced after that run, so the new number is
    optimistic (results.md shows both). Gate: booking top-1 may drop 2 points at most. Live spend under $0.001.
    The DATEV export uses the chosen accounts since R5-1 (issue #24)
  - History and rulebook for the agent (R3-4b; ADR-017, ADR-018, ADR-019, ADR-020 updated): MCP server
    `mcp-history` (third container, own role `invoiceguard_mcp_history`) with `get_invoice_history`,
    `search_similar_invoices` and `search_rulebook`. Migration 0013: `rulebook_chunks` (vector, `tsvector` with
    English and German stemmers, file SHA-256 as version) and three `security_barrier` views as the read model
    (`history_lines`: imported history and approved invoices that did not fail the injection check;
    `history_invoices`: their totals and payee IBAN; `invoice_item_names`), the role reads only those, the rulebook
    and three columns of `embeddings`; tests prove the rest is refused. Rulebook `docs/rulebook`: 10 files, 42
    sections, built into the api image (Compose `additional_contexts`), synced by `make index` and the demo reset
    with packaged vectors (tasks `document`/`query`). Agent: 10 allow-listed tools, a pattern per argument checked
    in code, `search_similar_invoices` takes `current` (the model never sees an invoice id), the api embeds rulebook
    questions and counts the cost in the agent's cap, prompt names history and rulebook as data. Evals: 10
    poisoned-history attack cases (54 in total), rulebook retrieval (20 questions, DE and EN), gate on rulebook
    hit@3. Live spend $0.352 of $0.45 (two attack runs and the two recorded demo runs)
    - **0 of 54 attacks succeeded** end to end and model only. Poisoned history: **delivered 0 of 10** as the agent
      runs (it read the history 3 times in 54 runs), so those runs tested nothing; with `get_invoice_history`
      called first (eval only) **10 of 10 delivered, 0 of 10 followed**, 7 findings name the injected line
    - Rulebook: **hit@3 90 % by vector** (English and German alike), MRR 0.81; full text without a key 90 %
      English, 50 % German
  - Done-when check (R4-1): `docs/results.md` holds real numbers from the full set (run of 2026-11-19 on
    `53dd6d9`), and the gate fails on a deliberate regression: draft PR #23 (closed, never merged) failed the eval
    gate ([run 44434817518](https://github.com/Ziad-Alghawi/invoiceguard/actions/runs/44434817518))

## Open decisions
- None for R1. Demo hosting and domain settled in ADR-014.

## Next
- R4 — Platform (PLAN.md §11), plan approved 2026-11-19, six PRs in this order:
  - R4-1: R3 wrap-up (done, see R3 above), CI hardening (every GitHub Action pinned to a commit SHA, Dependabot for actions, images built,
    scanned by Trivy and pushed to GHCR tagged with the commit SHA) and ADR-021 (k3s on the existing VPS, Caddy
    stays the edge and forwards to Traefik, Argo CD core, sealed-secrets, CD through a `demo` git tag).
    Done when: every `uses:` is a SHA; a fixable HIGH/CRITICAL finding fails the
    scan; images are in GHCR; ADR-021 merged and ADR-014 marked as partly superseded
  - R4-2: safety for several pods (done, three commits plus docs):
    - (a) Startup recovery only tries each invoice's advisory lock (`pg_try_advisory_xact_lock`, the key that
      every run and decision holds): a `processing` invoice is reset only when its lock is free, and the
      invoices another pod holds are skipped instead of waited for. Decisions wait at most
      `INVOICEGUARD_DECISION_LOCK_TIMEOUT_MS` (2 s) and answer `409`. ADR-007 and ADR-015 amended.
    - (b) ADR-022: migration 0014 adds `invoiceguard_app`, which has data rights only. It may only read and
      insert on the three logs, it cannot TRUNCATE, it has no CREATE, and it owns nothing. The api logs in as
      that role. A one-shot `migrate` Compose service runs Alembic and `invoiceguard-db-roles` as the owner
      before the api and the MCP servers start. `make demo-reset` runs in a one-off `migrate` container and
      refuses to run as the app role. The test suite runs the app as the app role. The Argo CD PreSync Job
      follows in R4-3.
    - (c) Per-IP login limit (ADR-011 amendment): 20 failed logins per address in 15 minutes, then `429` with
      `Retry-After`, before any account lookup or hashing. The failures are counted in a pruned
      `login_failures` table (migration 0015), so addresses are kept for the window only. The client address
      is taken from `X-Forwarded-For` only when a trusted proxy sent it (`INVOICEGUARD_TRUSTED_PROXIES`), and
      the web login action passes on Caddy's header.
    - Done-when check, each covered by a test:
      - two recoveries at once read each invoice once, and a held invoice is neither reset nor waited for;
      - a decision on a held invoice gets `409` after about 2 s;
      - the app role is refused TRUNCATE, DROP or DISABLE TRIGGER, DDL and UPDATE/DELETE on the logs (an
        `InsufficientPrivilege` error each time);
      - one address gets `429` while another logs in;
      - a spoofed `X-Forwarded-For` from an untrusted peer, or left of the proxy's entry, is ignored.
    - The stack was checked by hand, `make dev`: `migrate` exits 0; the api's connections are
      `invoiceguard_app`; seed works; demo-reset is refused in the api and works in `migrate`; 20 failures
      through the web container give `429` with `Retry-After: 899`, while another address still gets `401`.
    - Before the next demo deploy: add `INVOICEGUARD_APP_DB_PASSWORD` to the server's `.env`
      (`docs/deploy.md`).
    - Fix (#31, 2026-11-20): recovery reads an upload and releases the lock before extracting; the
      upload's own run then took the lock, found the invoice already read and returned before the
      extraction check, while recovery's extraction skipped the held lock. A run whose claim fails now
      still goes on to extraction (claimed, so once). Found as flaky CI on PR #30.
  - R4-3: Helm charts (done, ADR-023; ADR-021 and ADR-022 amended):
    - `infra/helm/invoiceguard-postgres`: PostgreSQL 16 with pgvector, a StatefulSet with a local volume and
      the image pinned by digest. It is installed first, because a hook runs before anything else in its
      release.
    - `infra/helm/invoiceguard`: api, web, validator (1 GiB limit) and the three MCP servers from GHCR by
      commit SHA (`image.tag` required), probes, and memory requests of about 1.2 GB in total, measured on
      k3d.
    - Pods run as numeric non-root users with a read-only root and no ServiceAccount token. The
      Dockerfiles name the same IDs (999, web 1000).
    - NetworkPolicies: only Traefik reaches web, only web reaches the api, only the api reaches the MCP
      servers and the validator, and only labelled clients reach PostgreSQL. Outgoing traffic is limited
      for web, the MCP servers and the validator.
    - Traefik ingress to web with a 413 above 11 MiB. `INVOICEGUARD_TRUSTED_PROXIES` is set to the pod
      network.
    - The migration as a `pre-install`/`pre-upgrade` hook (PreSync in Argo CD). The demo reset is a
      CronJob at 03:00 Europe/Berlin. Both run as the owner `invoiceguard_owner`, which is no superuser:
      the postgres chart creates it with `CREATEROLE`, together with the extensions, on first start. The
      migrations needed no change.
    - Secrets by name only (`invoiceguard-postgres`, `invoiceguard`); `docs/deploy.md` has a Kubernetes
      section.
    - Done-when check: the CI job `helm` lints and renders both charts, and fails if the chart renders
      without an image tag. It then installs both charts on k3d (k3s v1.36.6) with images built in the job
      and runs `.github/scripts/k3d-smoke-test.sh`, which checks:
      - the owner is no superuser;
      - the web page loads through Traefik, and a 12 MB body gets `413`;
      - `/health` and `/ready` answer;
      - the demo reset Job, run from the CronJob, loads the 6 samples with KoSIT passing;
      - the seeded user can log in;
      - the api reaches mcp-erp, and web and an unlabelled pod cannot;
      - `helm upgrade` runs the hook again.

      Checked by hand on a local k3d cluster first.
  - R4-4: cluster, Argo CD and CD (done, two PRs: #30 and #33; ADR-024, ADR-021 and ADR-014 amended):
    - The demo runs on k3s on the existing CX23 `invoiceguard` (4 GB; no 8 GB server was available at an
      acceptable price). Caddy stays the edge and forwards to Traefik's hostPort 8880 through Docker's bridge;
      Traefik trusts `X-Forwarded-For` from the pod network's gateway only, as measured with a `whoami` pod.
    - Argo CD core (no UI) follows the git tag `demo` with an app-of-apps: the namespace, the SealedSecrets,
      PostgreSQL, then the app with its PreSync migration hook. CI moves `demo` after every job of a `main`
      commit has passed and its images are in GHCR; the image tag is `$ARGOCD_APP_REVISION`.
    - The platform (k3s, Argo CD core, sealed-secrets) is installed by hand from pinned files checked by
      SHA-256; the bootstrap files add the `default` project (the core install has none), the child health
      check and a repo-server rendering one chart at a time. The sealing key has a backup off the server.
    - Cutover on 2026-11-20 (about an hour of downtime): the database (full and data-only dumps) and the uploads
      backed up and copied off the server, Compose stopped, the app synced, the data restored (all 26 tables
      matched), Caddy's site switched. The Compose deploy path (`docker-compose.prod.yml`, `make prod-up`,
      `prod-down`, `deploy`) is removed; `make demo-reset` now resets the local stack.
    - Done-when check:
      - the demo answers at the same URL from k3s; a login and the demo reset Job work;
      - the first failed login after the move recorded the visitor's real address, not `10.42.0.1`;
      - two reboot tests (before and after the cutover): k3s starts after Docker and everything comes back;
      - memory: 1.58 GB available before the cutover with Compose still running (gate: 1.2 GB), about
        1.3 to 1.4 GB after it;
      - a merge to `main` reaches the demo with no manual step: #33 merged as `314b325` on 2026-11-20; the
        job `demo-tag` moved the tag at 22:12:05 UTC, Argo CD synced at 22:15:54 UTC (3 min 49 s), the
        migration hook succeeded and all six deployments ran `314b325` images.
    - CI (job `helm`) now also bootstraps Argo CD core on k3d and lets it render the Applications at the commit,
      and starts k3s's Traefik with the server's settings; both tests failed first against the bugs they guard
      against (no default project; `hostIP` as the listen address).
    - Until 2026-11-23 the Compose volumes stay on the server as the fallback; then they are deleted (after
      asking).
  - R4-5: metrics (done, #34 and a follow-up for the server check; ADR-025):
    - `GET /metrics` on the api (`prometheus-client`): HTTP requests and latency by route template;
      invoices processed, check results, decisions and security events (committed rows only); LLM calls,
      cost, tokens and latency; agent runs; KoSIT calls and `invoiceguard_validator_up`. No invoice data in
      labels.
    - `infra/helm/invoiceguard-monitoring`: Prometheus v3.16.0 alone (no Alertmanager, node-exporter or
      kube-state-metrics), 30 s scrape, 7 days and 300 MB, `GOMEMLIMIT` 150 MiB, limit 192 Mi, DNS
      discovery of every api pod through a headless Service, no Ingress, nothing let in. Argo CD
      Application in sync wave 3.
    - Alert rules: 5xx share, cost cap or daily budget reached, validator down, api not scraped.
    - Grafana on the developer machine (`make grafana`, `infra/grafana/`) through an SSH tunnel and
      `kubectl port-forward`; the dashboard JSON is in the repo.
    - Done when:
      - [x] a CI test covers `/metrics` (`tests/test_metrics.py`, plus the validator and agent-run tests);
      - [x] each alert fires in a test (`promtool test rules` in the job `helm`; a broken copy of the rules
        made it fail);
      - [x] RAM measured on k3d first: Prometheus 31 to 37 MiB working set (94 MiB RSS), 901 series; the
        api 126 to 128 MiB, against 129 to 130 MiB for `main` (no measurable cost); Grafana showed the
        k3d data through a loopback-only port-forward;
      - [x] the PR is open with CI green (#34, merged as `3210d6a`);
      - [x] after the merge, on the server (2026-11-21, 18:26 UTC):
        - all four Applications Synced and Healthy at `3210d6a`;
        - Prometheus 30 Mi, `available` 1,245 MB against 1,320 MB before the deploy (gate: 1.0 GB), swap
          96 MB against 89 MB;
        - the api and the validator `up`, 145 `invoiceguard_*` series, demo traffic counted by route
          template, all four rules healthy and none firing;
        - the local Grafana showed the dashboard with the live data through the SSH tunnel.
    - On the deploy, the root app held back wave 3: the app stayed Progressing because its Ingress had no
      address. The server still had the Traefik settings from before #33, a platform file outside Argo CD
      that is copied by hand (docs/deploy.md). Copying it fixed the address, and the waves went on.
    - CI (job `helm`) now syncs the three chart Applications on k3d with the job's images, after Traefik has
      the server's settings, and waits until each is Synced and Healthy. With the Traefik settings from
      before #33 it failed on the app's Ingress; the root app is only compared (its SealedSecrets open only
      with the server's key).
  - R4-6: model comparison (done, #36, ADR-026):
    - Scope changed before the work started: three Gemini models on one key instead of Gemini vs Mistral
      (EU) vs Ollama, because of the budget (about €1 to €2 of Gemini credit, a hard stop at $0.50) and the
      4 GB server (no room for a local model next to the app). Mistral and Ollama stay the next step if
      EU-hosted inference becomes a requirement.
    - `invoiceguard-eval models` / `make eval-models`: the app's `PdfExtractor` with each model on 12 PDFs:
      the 6 demo samples drawn as PDFs (`packages/evals/datasets/demo`, truth from the demo XML, checked by
      a test) and the `small` set's 2 corpus and 4 generated PDFs. Table with field, document and line
      accuracy, accuracy per field, p50/p95 latency and cost per invoice in `docs/evals/model-comparison.md`.
      The eval gate replays it with `--check`.
    - The recording client's cap now keeps the dearest call so far (at least $0.02 here) free before each
      live call, and a live reply without a price stops the run.
    - Result (2026-11-21): flash-lite 100 % fields, 99.4 % line terms, p50 4.4 s, $0.0050; 3.8-flash
      100 % / 100 %, 8.6 s, $0.0053; 3.1-pro-preview 99.5 % / 100 %, 11.5 s, $0.0249. gemini-3.8-flash stays
      the default. Spent $0.389 ($0.040 smoke, $0.348 full run).
  - Cut from R4: self-hosted Langfuse and the trace ID in the UI (`model_calls` covers cost and latency), n8n,
    paid EU endpoints and large Ollama models, the full kube-prometheus-stack
- R5 — Polish and story (PLAN.md §11). Done and open (sizes: XS < 1 h, S one session, M two, L three or more):
  - R5-1: issue #24, DATEV export per chosen account and VAT rate (done, PR #37 merged; ADR-013 amended):
    - One row per (chosen account, VAT rate): net from the line amounts (BT-131), tax per rate on the rate's sum
      (as BT-117), the rounding cent of a rate split over several accounts on its largest row; Soll/Haben per
      row. Used only when there is no document allowance or charge and the rows match BT-109, BT-110 and BT-112.
    - Otherwise one row as before (the single chosen account, else the expense account), counted as
      `without_account_split` in the response, the audit event and the web message. No migration.
    - Done-when check: golden files for one account, two accounts and two VAT rates; unit tests for the rounding
      cent, tax per rate, a line without a rate, a discount line and each failed check; API tests for an
      uploaded invoice approved with two accounts, mixed rates, a credit note and both fallbacks.
  - R5-2: litellm 1.108.1 → 1.110.1, a separate small PR on or after 2026-11-26 (1.110.1 was published on
    2026-11-19; ADR-004 asks for a week). Changelog, price table for the three Gemini models and the embedding
    model, `make check`, `make test`, eval-gate replays (`small`, `full`, `eval-models --check`); filelock to
    4.2.1 and the CVE-2026-112940 entry out of `.trivyignore` (expires 2026-12-19). (S)
  - R5-3: German UI (done, in review; ADR-027):
    - next-intl 4.15.1 pinned exactly, without locale routing: German by default, a DE | EN switch in the header
      and on the login page, the choice in the `NEXT_LOCALE` cookie for a year, paths unchanged. Three
      `@eloqnt/*` packages pinned to older releases in `pnpm-workspace.yaml` (newest under a week old).
    - Every page and component reads `messages/de.json` / `messages/en.json`; helpers return message keys
      instead of English sentences. API codes (statuses, check types, roles, audit actions, security event
      types, field names) have labels in both languages; dates follow the language in Europe/Berlin time.
    - `cacheComponents`: the locale is read inside a Suspense boundary in the root layout; an inline script sets
      `<html lang>` before the first paint. The production build still prerenders a shell for every page.
    - Texts written by the API stay English (check messages, status reasons, API errors, the agent's finding),
      listed as a limitation in the README.
    - Done-when check: `messages.test.ts` (same keys, no empty text, every message formats), `codes.test.ts`
      (every code in the API's Python source has a label in both languages; both checked to fail on a removed
      key), typed keys in `tsc`, ESLint `react/jsx-no-literals`; the 7 Playwright tests pass in German on
      `make dev`, including the new `language.spec.ts` (switch, reload, login in English, back to German).
  - Possible later task: translate the API's own texts (a message code with parameters for each check result,
    status reason and error, rendered by the web in the user's language). (M)
  - README: English pass and the German section (now "Kommt in R5"). (M)
  - Architecture diagram as an image for the README. (S)
  - README results, limitations and roadmap refreshed after R4. (S)
  - 90-second demo video (poisoned invoice caught) and `docs/demo-script.md`. (M, recording by Ziad)
  - `docs/interview-notes.md`, the interview Q&A sheet. (M)
  - `SECURITY.md` and a short `CONTRIBUTING.md`. (S)
  - Three LinkedIn posts, CV bullets, cover-letter paragraph. (S to M, outside the repo)
  - Release tag and GitHub Release with screenshots (PLAN.md §8). (S)
  - Drop the zlib `.trivyignore` entry (CVE-2026-85091) once python:3.12-slim ships the Debian fix. (XS, waiting)
  - Delete the Compose volumes on the server after 2026-11-23, after asking. (XS)
- Backlog: scan-like generated PDFs (image noise, no text layer) for the eval set

## Known limitations
- Exception agent (ADR-018): the cost cap is checked before each call, so the last call can overshoot it; the
  transcript is sent again each step (input grows with the steps); the model sees the tool contracts from the prompt,
  not their JSON schemas; findings are not evaluated yet (R3). Recorded demo runs go stale if the seed changes.
  Starting a live run is open to any logged-in user (no rate limit beyond the cost cap and the daily budget).
- MCP servers (ADR-017): no authentication between the api and the servers (reachable only inside the stack); one
  database connection per tool call; the migration needs a user that may create roles.
- History tools (R3-4b): the agent rarely reads the history on its own (3 of 54 runs), so the history mostly adds
  nothing to its findings yet; the poisoned-history cases measure the model only with the history forced in.
  The history is generated and clean; `search_similar_invoices` matches line by line (vector or trigram), not
  whole invoices. Rulebook questions without a key (full text) find the German answers only half the time. A
  changed rulebook section needs new packaged vectors or is found by full text only.
- Review (ADR-016): approvals are final; a rejected invoice can be reopened, which runs the checks (and for a plain
  PDF the LLM extraction) again, so a reopen costs what the first run cost. On the public demo one visitor can use
  both the reviewer and the approver account, so four eyes there shows the mechanism, not real separation of duties.
  Roles are set by `make seed-user`; there is no user administration.
- Graph (ADR-015): startup reads the thread of every invoice waiting for review (one query each); each graph run
  opens its own database connection for the checkpointer; a decision made while a run (an LLM extraction) holds
  the invoice's lock gets `409` after 2 s (R4-2), and the user has to click again.
- Injection scan (R2-4): heuristics only, so new wordings or other languages get through: R3-3 measured 14 of 44
  attack texts flagged, none of the indirect ones. No attack succeeded, so no LLM classifier (ADR-002). White and
  tiny text is in the text layer and scanned like any other, but hiding it is not itself a signal; text in images
  (scans without a text layer are `skipped`) and invisible PDF text (render mode 3, skipped on purpose: OCR'd scans
  use it) are not seen. The security log has no alerting or retention yet.
- Login lockout is per account: anyone who knows a demo email can lock it for 15 minutes, and the `429` reveals that
  the account exists.
- The per-IP login limit (R4-2) has these gaps:
  - Failures are counted without a lock, so parallel attempts can pass it by a few.
  - Users behind one shared address (an office NAT) share the limit.
  - Compose (dev) trusts `X-Forwarded-For` from Docker's private ranges, and the api's published port is
    reached through the Docker gateway, so a local caller can set any address. On the demo the api is not
    public; if Docker's NAT changes, the address Traefik sees for Caddy may change too (ADR-024).
- Database roles (ADR-022, ADR-023): the api runs as the restricted `invoiceguard_app`. In Kubernetes the
  migrator is the non-superuser owner `invoiceguard_owner`. Compose (dev) still
  migrates as `POSTGRES_USER`, a superuser in the official PostgreSQL image. In Kubernetes a new untrusted
  extension needs the superuser once, by hand: the init script runs on an empty volume only. A new
  append-only table gets UPDATE and DELETE from the default privileges and must revoke them in its migration.
- Helm (ADR-023): the uploads volume is ReadWriteOnce, so the api pods and the demo reset must share one node.
  The CI job builds the six images again instead of reusing those of the `images` job.
- Upload limit (R2-7): counted from the audit log without a lock, so parallel uploads can pass it by a few files; the
  demo accounts are shared, so on the demo it caps all visitors together. One file per upload (no bulk upload);
  there is no sample picker: visitors bring their own XRechnung or ZUGFeRD file.
- Demo (ADR-014, ADR-021, ADR-024): one VPS with 4 GB (about 1.3 GB available at idle, so Prometheus stays
  small and Grafana runs on the developer machine, ADR-025), no backups (sample data, reset nightly); the shared demo login can be locked for 15
  minutes by anyone, the nightly reset unlocks it. The Hetzner firewall is the only layer in front of ports 8880,
  6443 and 10250. Platform upgrades (k3s, Argo CD, sealed-secrets) are manual, with new pins and hashes.
- Metrics (ADR-025): counters live in the api process and restart at 0 with it; rows written by the nightly
  reset CronJob and the migration hook are not counted. No Alertmanager: a firing alert shows in Prometheus and
  Grafana, and nobody is notified. The LLM panels stay at 0 on the demo (no model key).
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
  more, so the `low_confidence` check (below 0.8) caught 1 of them; with the 0.9 default it catches 5 of 9 (4 were
  given 0.9 or more); on the 10 conflicting-value cases the model picked the right value but never lowered its
  confidence.
- Eval (ADR-019): generated layouts are cleaner than real invoices, the corpus has 12 PDFs, the fraud set uses
  the demo seed only; scan-like PDFs are in the backlog. Calls that failed live are not recorded, so a replay of
  such a run needs `--missing-as-failed`.
- The daily LLM budget is checked before each extraction, so parallel extractions can overshoot it by one invoice
  each; PDFs it held back wait until the API restarts (no scheduler). No per-invoice cap yet (R2).
- A PDF the model cannot read a required term from (invoice number, date, totals) ends in `failed`, not in review.
- DATEV export (ADR-013): not certified and not yet imported into a real DATEV installation; rows per chosen
  account and VAT rate only when the lines add up to the totals (no document allowance or charge), else one row
  the advisor splits; without chosen accounts one row per invoice, so several VAT rates (or a line without a rate)
  mean no BU key; one collective creditor until creditor numbers; a rate split over several accounts can differ
  by a cent from BT-117 once DATEV computes the tax per row; no exchange rate for non-EUR invoices; disallowed
  characters in the invoice number become `-` in Belegfeld 1.

- Booking suggestions (ADR-020): measured on a generated history with clean, distinct wordings per item (62
  test lines), not on a real ledger; the vote was changed once after seeing that set. Lines of a visitor's upload
  on the demo (no key) use the text match. Suggestions are computed on every `GET .../bookings` (an exact scan,
  milliseconds at thousands of bookings; no vector index yet). Lines embedded while the key was missing or the
  budget used up wait for `make index`.

## Lessons learned
- Recorded replay needs prompts that are identical across runs: keep generated ids and timestamps away from the
  model. Measure whether an attack was delivered before counting it as defended; a tool the agent never calls tests
  nothing.
- Embedding similarities are compressed (unrelated texts still score ~0.8): do not use raw cosine scores as vote
  weights; and with NULL on both sides, `IS DISTINCT FROM` is false, so test a filter with its parameter absent.
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
