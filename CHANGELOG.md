# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- German UI (R5, ADR-027): every page of the web app in German and English with next-intl 4.15.1. German is the
  default; a DE | EN switch in the header and on the login page keeps the choice in a cookie, and the paths stay the
  same. Statuses, check types, roles, audit actions, security event types and field names have labels in both
  languages; dates follow the language (Europe/Berlin time). Texts from the API stay English. A test fails when
  the two message files differ in keys or a message does not format, another when a code in the API's source has
  no label, `tsc` fails on an unknown key, and ESLint fails on text written into JSX. The Playwright tests run in
  German, and a new one switches to English and back. A translated not-found page.

### Fixed
- The queue, the invoice page, the history and the upload page showed the reasons processing writes in English
  in the German UI ("Failed checks: po_match."). The API now returns `status_reason_code` and
  `status_reason_checks` with invoices and `reason_code` and `reason_checks` with audit events
  (`status_reasons.py`, ADR-027 amended), and the web shows them in the chosen language with the check names.

### Changed
- DATEV export per chosen account (issue #24, ADR-013 amended): an invoice approved with accounts per line gets one
  booking row per (account, VAT rate), with the chosen account as Gegenkonto, the BU key of the rate and the
  gross amount from the line net amounts. The tax is computed per rate (as BT-117) and the rounding cent of a
  rate split over several accounts goes to its largest row. The split is used only when there is no document
  allowance or charge and the rows match BT-109, BT-110 and BT-112; otherwise the invoice keeps one row (the
  single chosen account, else `INVOICEGUARD_DATEV_EXPENSE_ACCOUNT`) and is counted as `without_account_split` in
  the response, the audit event and the web app's message. Invoices approved without accounts are unchanged.

### Added
- Model comparison (R4-6, ADR-026): `invoiceguard-eval models` and `make eval-models` run the app's PDF
  extraction with `gemini-3.5-flash-lite`, `gemini-3.8-flash` and `gemini-3.1-pro-preview` on 12 PDFs (the 6
  demo samples drawn as PDFs, new in `packages/evals/datasets/demo`, and 6 from the `small` set). The table
  is in `docs/evals/model-comparison.md`: accuracy overall and per field, p50/p95 latency, cost per invoice.
  The eval gate replays it with `--check`. `gemini-3.8-flash` stays the default.
- Metrics (R4-5, ADR-025):
  - `GET /metrics` on the api (`prometheus-client`). It covers:
    - HTTP requests and latency by route template;
    - invoices processed by outcome, check results, review decisions and security events;
    - LLM calls, cost, tokens and latency, and exception agent runs by status and stop reason;
    - KoSIT calls by outcome, and `invoiceguard_validator_up` from the validator's health endpoint.

    The business counters count committed rows only, and no label holds invoice data.
  - `infra/helm/invoiceguard-monitoring`: Prometheus v3.16.0 pinned by digest. It scrapes every 30 s and
    keeps 7 days (300 MB cap), with `GOMEMLIMIT` and a 192 Mi limit. It finds every api pod through a new
    headless Service. It has no Ingress, and a NetworkPolicy lets nothing in. Argo CD deploys it after the
    app (sync wave 3).
  - Alert rules: 5xx share, cost cap or daily budget reached, validator down, api not scraped. There is
    no Alertmanager.
  - `infra/grafana/` and `make grafana`: a local Grafana with the provisioned **InvoiceGuard** dashboard,
    reading the demo's Prometheus through an SSH tunnel.
  - CI (job `helm`): `promtool check config` and `promtool test rules` (each alert fires in a unit test);
    on k3d, Prometheus scrapes the api and the web pod cannot reach it.
  - CI (job `helm`): the Argo CD test now syncs the three chart Applications with the job's images, after
    Traefik has the server's settings, and fails unless each ends Synced and Healthy. The root app's sync
    waves wait for that health, so an app stuck Progressing would hold back the ones after it.
  - Verified on the demo: Prometheus at 30 Mi, `available` 1,245 MB (gate 1.0 GB), live metrics in the
    local Grafana.
- The demo on k3s with Argo CD (R4-4, ADR-021, ADR-024):
  - `infra/k3s/`: k3s settings for the 4 GB server (no ServiceLB, encrypted Secrets, kubelet memory
    reservations), Traefik's hostPort 8880 with trusted forwarded headers from the pod network's gateway and
    the Ingress address 127.0.0.1, a systemd drop-in that starts k3s after Docker, `fetch.sh` (pinned release
    files checked by SHA-256) and `seal-secrets.sh`.
  - `infra/argocd/`: the root Application on the git tag `demo`, sync waves (namespace, SealedSecrets,
    PostgreSQL, app), the image tag from `$ARGOCD_APP_REVISION`; bootstrap files for the core install (the
    `default` project, the child health check, one chart rendered at a time).
  - CD: the CI job `demo-tag` moves `demo` to a `main` commit once every job has passed; Argo CD deploys it.
  - CI (job `helm`): the pinned files' hashes, a dry run of the manifests, Argo CD core bootstrapping and
    rendering the Applications at the commit, and k3s's Traefik started with the server's settings, on k3d.
  - `docs/deploy.md` rewritten for the cluster: how a change reaches the demo, operating, secrets and the
    sealing key, rollback by moving the tag, and the server set up from scratch.
- Helm charts (R4-3, ADR-023):
  - `infra/helm/invoiceguard-postgres`: PostgreSQL 16 with pgvector, pinned by digest. On first start it
    creates the owner `invoiceguard_owner`, which is no superuser, its database and the extensions.
  - `infra/helm/invoiceguard`: api, web, validator and the three MCP servers from GHCR by commit SHA, with
    probes, memory requests and limits, numeric non-root users and read-only root filesystems.
  - The migration runs as a `pre-install`/`pre-upgrade` hook (PreSync in Argo CD); the demo reset is a
    nightly CronJob. Both run as the owner.
  - NetworkPolicies (only the api reaches the MCP servers), a Traefik ingress with a 413 above 11 MiB, and
    secrets referenced by name only.
  - CI job `helm`: lint, render, and install on k3d with a smoke test (`.github/scripts/k3d-smoke-test.sh`).
  - The Dockerfiles set numeric user IDs (the same as before), so Kubernetes can check `runAsNonRoot`.
  - ADR-021 and ADR-022 amended; `docs/deploy.md` has a Kubernetes section.
- Several api pods safely (R4-2):
  - Startup recovery only tries each invoice's advisory lock: it skips the invoices another pod holds and
    resets a `processing` invoice only when nobody holds its lock.
  - Review decisions wait at most `INVOICEGUARD_DECISION_LOCK_TIMEOUT_MS` (2 s), then answer `409`.
  - ADR-007 and ADR-015 amended.
- Restricted database role for the api (R4-2, ADR-022):
  - Migration 0014 adds `invoiceguard_app`, with data rights only. It may only read and insert on
    `audit_events`, `security_events` and `model_calls`. It has no TRUNCATE and no CREATE, and it owns nothing,
    so it cannot drop or disable the append-only triggers.
  - A one-shot `migrate` Compose service runs Alembic and `invoiceguard-db-roles` as the owner before the api and
    the MCP servers start.
  - `make demo-reset` runs as the owner in a one-off `migrate` container and refuses to run as the app role.
  - Each `.env` now needs `INVOICEGUARD_APP_DB_PASSWORD` (Compose refuses to start without it).
- Per-IP login limit (R4-2, ADR-011 amendment):
  - 20 failed logins from one address in 15 minutes, then `429` with `Retry-After`, before any account lookup.
  - Counted in a pruned `login_failures` table (migration 0015), so addresses are kept for the window only.
  - A refused attempt is logged as the security event `login_rate_limited`, without the address.
  - The client address comes from `X-Forwarded-For` only when the peer is in `INVOICEGUARD_TRUSTED_PROXIES`.
    The web login action passes on the header Caddy set.
- ADR-021: the R4 platform (k3s on the demo VPS rescaled to CX33, Caddy in front of Traefik, Argo CD following a
  `demo` tag, Alembic as a PreSync Job, sealed-secrets) and what R4 cuts; ADR-014's hosting is partly superseded.
- Container images in CI (R4-1): all six images built, scanned by Trivy 0.76.2 (its image pinned by digest, not
  `trivy-action`; fixable HIGH and CRITICAL findings fail the job, accepted ones in `.trivyignore` with a reason
  and an expiry date) and pushed to GHCR on `main`, tagged with the commit SHA.
- CI hardening (R4-1): every GitHub Action pinned to a full commit SHA with its version in a comment, a CI job
  that fails on an unpinned action, Dependabot updates for the pins.
- R3 closed (R4-1): the eval gate is shown to fail on a deliberate regression (draft PR #23, never merged);
  the R4 plan in `docs/status.md`.
- History and rulebook for the exception agent (R3-4b; ADR-017, ADR-018, ADR-019, ADR-020 updated): a third
  read-only MCP server, `mcp-history`, with `get_invoice_history`, `search_similar_invoices` and `search_rulebook`.
  Its database role reads three views of approved, injection-free history, the rulebook and the vectors of
  `embeddings`, nothing of the invoices (migration 0013). A short rulebook in `docs/rulebook` (10 files, 42
  sections: what each check means, thresholds, how to resolve it, SKR03 guidance), synced by `make index` and the
  demo reset with packaged vectors. The agent has 10 allow-listed tools with a pattern per argument, never sees an
  invoice id, and has rulebook questions embedded by the api (cost counted in its cap); full text without a key.
  Evals: 10 poisoned-history attack cases (0 of 10 delivered as the agent runs; 10 of 10 delivered and 0 followed
  with the history forced in; 0 of 54 attacks succeeded), rulebook retrieval on 20 DE/EN questions (hit@3 90 % by
  vector, 70 % by full text), and a gate rule on rulebook hit@3. New container and secret
  `INVOICEGUARD_MCP_HISTORY_DB_PASSWORD` (`docs/deploy.md`). Live spend $0.352.
- Booking suggestions (R3-4a, ADR-020): pgvector in our PostgreSQL (migration 0012: `embeddings`, `bookings`,
  extensions `vector` and `pg_trgm`). The lines of a new invoice are embedded after processing
  (`gemini/gemini-embedding-001`, 768 dimensions, through LiteLLM; logged and within the daily budget); a line
  without a vector uses a trigram text match. `GET /invoices/{id}/bookings` suggests an SKR03 account per line
  from the 10 most similar booked lines (same supplier preferred) with the bookings it rests on; no chat model.
  `/approve` and `/override/confirm` take the account per line, stored with the decision and the top suggestion,
  and the approved lines are indexed at once (an invoice flagged for prompt injection is never retrieved). Web:
  one account dropdown per line, preselected with the suggestion and its evidence. `make index`
  (`invoiceguard-index`) imports a generated booking history with packaged vectors (the demo reset does too) and
  embeds what is missing. Eval part `bookings`: **98.4 % top-1 / 100 % top-3 by vector** on 62 held-out lines
  (text match 91.9 %, the supplier's most frequent account 45.2 %); the gate fails on a drop over 2 points.
  Live spend under $0.001. The DATEV export does not use the chosen accounts yet (#24).
- Attack set and CI eval gate (R3-3, ADR-019 updated): 44 prompt-injection cases in `packages/evals`
  (`attacks.py`), each a poisoned twin of a generated invoice, with the text in PDF text (visible, white, 1 pt),
  supplier and item names, XML notes or the filename. They run through the app and, when blocked, through the
  real exception agent with the real MCP servers in process; scored end to end and model only. One live run
  ($0.31), replayed: 0 of 44 succeeded either way, the heuristic scan flagged 14 of 44. Workflow `eval-gate`
  (replay only, no key: `small` on PRs touching prompts, agent, checks, parsers, MCP servers or the evals, `full`
  nightly) and `make eval-gate` fail on a field-accuracy drop over 2 points, any successful attack, or cost per
  invoice up more than 25 % against `packages/evals/baselines/`. The fraud set is rerun on the eval database
  at threshold 0.9 (10 of 10 as expected).
- Eval harness (R3-2, ADR-019): `packages/evals` and `make eval`. Pinned public datasets (KoSIT testsuite, FeRD
  ZUGFeRD samples, SHA-256 checked, not committed), 17 generated German invoices with UBL twins and truth,
  recorded model replies (replay free and offline, `--live` under a spend cap), parser, extraction, confidence
  and decision metrics, `docs/results.md`. CI job `evals`. Baseline at reasoning effort `low`: 99.2 % of document
  terms right on completed extractions, $0.0058 per invoice, the fraud set decided as expected as XML and as
  PDF; `low` stays the default (ADR-010 updated).
- R3 plan: three rounds (R3-2 eval harness and extraction results, R3-3 attack set and CI gate, R3-4 RAG and the
  history tools) and ADR-019 (evaluation harness with pinned datasets and recorded model replies).
- Reopening rejected invoices (R2-7, ADR-016 updated): `POST /invoices/{id}/reopen` with a required reason, for
  reviewers and approvers; approved invoices are never reopened (`409`). The decision resumes the invoice's thread
  under the advisory lock; `decide` writes `rejected → processing` and one `invoice.reopened` audit row in one
  transaction, clears the old fields and checks, and routes to `read` (new edge), so the invoice is checked again on
  the current master data and pauses at review. Plain PDFs are extracted again (with a key and budget); blocked
  results are investigated as after an upload. Web: "Reopen" form with a reason on rejected invoices. Tests for one
  audit row, fresh checks after a master-data change, `409` for approved, `422` without a reason, two reopens at
  once; Playwright test rejects and reopens an invoice.
- Upload page (R2-7): `/upload` for every logged-in user, linked in the header. The browser sends the file with
  upload progress to a route handler (`/upload/file`), which passes it on to `POST /invoices` with the session;
  the page then waits for processing and links to the new invoice. Clear messages for a wrong type, a too large
  file, a duplicate (with a link to the existing invoice), the demo rule and the hourly limit. Demo mode refuses a
  PDF without embedded XML at upload (`422`, nothing stored). New setting `INVOICEGUARD_UPLOAD_MAX_PER_HOUR`
  (uploads per user per hour, `429` above; unset = no limit, 30 on the demo). Playwright test for the upload page.
- Exception agent (R2-6, ADR-018): investigates blocked invoices with the read-only MCP tools and returns an English
  finding and a German email draft to the supplier (recipient from `suppliers.contact_email`); it never changes the
  invoice. Own bounded loop over `LLMClient` (one schema-validated JSON action per step, tool names as an enum and
  again in code), limits from `INVOICEGUARD_AGENT_*`: 8 steps, 12 tool calls, 90 s, $0.05 per invoice across runs;
  the daily budget is checked before a run. Invoice fields, bounded check evidence and tool results are passed as
  untrusted JSON between markers; injection-flagged invoices are never sent. Runs outside the processing graph as a
  background task after an invoice ends `blocked`, and on `POST /invoices/{id}/investigate`;
  `GET /invoices/{id}/investigation` returns the latest run. Migration 0011: `agent_runs` and `agent_steps` (every
  model and tool call with tokens, cost, latency), model calls in `model_calls` (purpose `agent`); interrupted runs
  are failed at startup. Without a model key the button loads a recorded real run for the case (samples 02 and 03,
  `scripts/record_agent_run.py`). Web: investigation section with finding, copyable email draft, steps and totals.
  Playwright test for "Investigate"; dependency `mcp` 2.3.0 in the api.
- Read-only MCP servers (R2-5, ADR-017): `apps/mcp-erp` (`get_supplier`, `list_purchase_orders`, `get_purchase_order`
  with received quantities, `get_goods_receipts`) and `apps/mcp-registry` (`check_vat_id`, `check_iban`,
  `get_bank_accounts`), MCP Python SDK 2.3.0 over streamable HTTP, typed inputs with patterns and typed outputs, fixed
  SQL in `READ ONLY` transactions. Migration 0010: tables `goods_receipts` and `goods_receipt_lines`, column
  `suppliers.contact_email`, roles `invoiceguard_mcp_erp` and `invoiceguard_mcp_registry` with `SELECT` on their own
  tables (the registry on four supplier columns only). `invoiceguard-db-roles` sets their passwords from
  `INVOICEGUARD_MCP_ERP_DB_PASSWORD` / `INVOICEGUARD_MCP_REGISTRY_DB_PASSWORD` at api start (required by Compose).
  Demo seed with contact emails and goods receipts. Tests: each role reads only its tables and columns and cannot
  write; tool tests as the role; CI job per server and a smoke call in the Compose test.
- Security events and prompt-injection scan (R2-4): append-only `security_events` table (migration 0009) for failed
  logins, lockouts, refused role checks, self-approval attempts and injection hits; `GET /security-events` and the
  web page `/security` for approvers. Heuristic scan of the invoice text (XML and PDF text layer, English and German
  instruction phrases, invisible Unicode characters, no LLM); a hit fails the new `prompt_injection` check, blocks
  the invoice and logs an `injection_suspected` event. Demo sample 06 with an injected note. Playwright test for the
  poisoned upload and the security page.
- Four-eyes override (R2-3, ADR-016): user roles `reviewer` / `approver` and the status `override_requested`
  (migration 0008, existing users become reviewers). `POST /invoices/{id}/override` (any user, reason required),
  `/override/confirm` and `/override/decline` (a different user with the approver role, reason required; `403`
  for reviewers and the requester). Each step resumes the paused graph thread under the per-invoice lock, and the
  `decide` node writes the status and one audit row (`invoice.override_requested`, `invoice.override_confirmed`,
  `invoice.override_declined`), checking the role and the requester again. `GET /auth/me` returns the role.
  `make seed-user` also seeds an approver from `INVOICEGUARD_SEED_APPROVER_*` and takes
  `INVOICEGUARD_SEED_USER_ROLE`. Web: override request, confirm and decline in the decision panel, role in the
  header, "Override requested" queue tab, both demo accounts on the login page (`DEMO_APPROVER_*`). Playwright
  test for the override flow.
- `make deploy`: pulls `main` and runs `make prod-up` on the demo server over SSH; the target comes from
  `DEPLOY_HOST` in the local `.env`, and the command refuses to run without it (`docs/deploy.md` section 6).
- Processing graph (R2-2, ADR-015): processing runs as a LangGraph graph per invoice (`read` / `extract` → `checks` →
  `review` → `decide`, thread ID = invoice ID), checkpointed by `PostgresSaver` in the `langgraph` schema (migration
  0007). Every run pauses at `review` with `interrupt()`; approve and reject resume it with `Command(resume=...)`
  under a per-invoice advisory lock, and only `decide` writes `approved` / `rejected` with its audit rows. Pauses
  survive API restarts; startup gives invoices from before the graph a paused thread; the demo reset deletes
  threads. Same statuses, rules, responses and audit events as before. Dependencies `langgraph` 1.2.20 and
  `langgraph-checkpoint-postgres` 3.2.0.
- ADR-015 (processing graph with LangGraph, approval as `interrupt()`) and ADR-016 (four-eyes override of blocked
  invoices, reopening rejected invoices); R2 plan in `docs/status.md`.
- Public demo deployment (ADR-014, `docs/deploy.md`): `infra/edge` is a shared Caddy for every site on the server
  (the only public ports, automatic Let's Encrypt HTTPS, shared security headers, no access log, one file per site);
  `infra/docker-compose.prod.yml` removes all host ports, attaches the web container to its `edge` network, sets
  `INVOICEGUARD_ENV=prod` for Secure cookies, restart policies, log rotation and a 1 GB memory limit for the
  validator. `make prod-up`, `make prod-down`, `make demo-reset`.
- Daily LLM budget (`INVOICEGUARD_LLM_DAILY_BUDGET_USD`, summed from `model_calls` per UTC day): once reached, PDFs stay
  in `awaiting_extraction` with a reason and an `invoice.extraction_deferred` audit event, without calling the model.
- Demo reset (`invoiceguard-demo-reset`, only with `INVOICEGUARD_DEMO_MODE=true`): deletes invoices, exports and
  files, keeps the append-only audit log (plus a `demo.reset` event) and LLM costs, restores the master data and
  processes five packaged sample invoices (ready, changed IBAN, PO overcharge, CII, unknown supplier).
- Web: the login page shows the shared demo account when `DEMO_LOGIN_EMAIL` and `DEMO_LOGIN_PASSWORD` are set.
- CI: validates the prod override, the shared Caddy and its sites, and runs the demo reset in the built image.
- README: description, demo link, screenshots, architecture diagram, features, tech stack, honest limits.

- DATEV-style export (ADR-013): `POST /exports/datev` writes the approved, not yet exported invoices of the oldest
  waiting fiscal year into an `EXTF` Buchungsstapel file (format 700/13, Windows-1252, CRLF, `;`, decimal comma, DDMM
  document date, one row per invoice: gross amount, Soll/Haben, creditor and expense account, BU key for a single
  configured VAT rate, Belegfeld 1, Buchungstext) and returns the count, how many have no tax key and how many are
  left for another fiscal year; `GET /exports/datev/{id}/file` downloads the stored file again. Settings
  `INVOICEGUARD_DATEV_*` (advisor and client number, fiscal year start, account length, chart, accounts, tax keys as
  JSON). Audit events `datev_export.created`, `invoice.exported`, `datev_export.downloaded`.
- Migration 0006: `datev_exports` (the stored files) and `invoices.datev_export_id`; exports lock the invoices
  `FOR UPDATE`, so an invoice is never in two files.
- Web: "Export to DATEV" on the queue starts the download and shows the count, with "Download again".
- Playwright end-to-end test (`make e2e`, CI job `e2e` on Docker Compose, no LLM calls): login, reject the
  changed-IBAN invoice, approve a clean one, export and check the downloaded file. `@playwright/test` 1.64.1
  (pinned; the newer 1.65 releases were days old).
- Tests: DATEV field formatting, encoding and a golden file; export rules (no double export, only approved, one
  fiscal year per file, tax keys, settings, parallel exports, audit).

- Login with seeded users (ADR-006, ADR-011): `POST /auth/login`, `/auth/logout`, `GET /auth/me`; Argon2id password
  hashes (`argon2-cffi`); server-side sessions (only the token's SHA-256 is stored) in an HttpOnly, SameSite=Lax cookie,
  Secure in prod; 5 failed logins in a row lock the account for 15 minutes (`429` with `Retry-After`). Settings
  `INVOICEGUARD_SESSION_TTL_MINUTES`, `INVOICEGUARD_LOGIN_MAX_FAILURES`, `INVOICEGUARD_LOGIN_LOCKOUT_MINUTES`.
- `invoiceguard-seed-user` / `make seed-user`: creates or resets a user from `INVOICEGUARD_SEED_USER_*`; the password
  comes from the environment only.
- Review API (ADR-012): every invoice endpoint needs a login; `POST /invoices/{id}/approve` (a `blocked` invoice only
  with `override_reason`), `POST /invoices/{id}/reject` (reason required), statuses `approved` and `rejected`;
  `GET /invoices` filters by `status` and returns `X-Total-Count`; `GET /invoices/{id}` returns the fields with
  `low_confidence` flags and a `file_url`; `GET /invoices/{id}/file` downloads the original; `GET /invoices/{id}/audit`.
- Migration 0005: `users`, `sessions`, the two review statuses, and on `audit_events` the user, status before and
  after and reason as columns (existing status events moved there) plus a trigger that rejects `UPDATE` and `DELETE`.
  Login, logout, failed login, lockout, upload (now attributed to the user), override, approve and reject are audited.
- Web review UI: login page, queue with status filters and paging, invoice page with check results, extracted fields
  (low-confidence ones highlighted with evidence), download, approve / approve with override / reject, and audit
  history; the web server forwards the session to the API (backend for frontend).
- CI smoke test logs in with a generated seed password and approves, overrides and checks the audit rows.
- ADR-011 (sessions and lockout), ADR-012 (review decisions in R1), ADR-007 amendment (review statuses).
- LLM extraction of plain PDF invoices (ADR-010): Gemini Flash reads the PDF and answers in a strict schema with a
  value, confidence and evidence (page, snippet) per field and per line; one retry on invalid output, then
  `failed`; fields stored with `source=llm`. Flow `awaiting_extraction → processing → ready / blocked / failed`
  with an atomic claim, audit events and startup recovery; without an API key PDFs wait with a reason.
- `LLMClient` interface with a LiteLLM implementation (ADR-004); LiteLLM 1.108.1 pinned, its bundled price table
  only (no download at import), and no `.env` loading at import (`LITELLM_MODE=PRODUCTION`).
- `low_confidence` check: fields below `INVOICEGUARD_EXTRACTION_CONFIDENCE_THRESHOLD` warn; a low-confidence payee
  IBAN or total blocks the invoice.
- Cost log: migration 0004 with `model_calls` (tokens, cost, latency, status per call, also failed ones) and
  `invoice_fields.evidence`; an unknown model price fails the extraction; `GET /invoices/{id}` returns `llm_calls`
  and `llm_cost_usd`.
- Prompt-injection boundary for extraction: constant system prompt, document only between untrusted markers in the
  user message, schema with no extra keys, rejection reasons without document text; tested with an injection PDF.
- `scripts/extract_pdfs.py`: manual run against the real model with fields, confidence, cost and time per PDF.
- Settings `INVOICEGUARD_LLM_API_KEY`, `INVOICEGUARD_EXTRACTION_MODEL`, `INVOICEGUARD_LLM_TIMEOUT_SECONDS`,
  `INVOICEGUARD_EXTRACTION_CONFIDENCE_THRESHOLD`, `INVOICEGUARD_EXTRACTION_REASONING_EFFORT` (thinking level,
  default `low`); empty environment variables now count as unset.
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

### Fixed
- Startup recovery could leave an uploaded plain PDF in `awaiting_extraction` (#31): a run that finds the
  invoice already read, by recovery, now still goes on to extraction, which claims the invoice, so it is
  extracted once. Found as flaky CI; covered by two deterministic tests.
- Injection scan docstring and known limitations: white and tiny PDF text is in the text layer and scanned like
  visible text (the attack set showed it); the earlier note said it was not seen.
- Eval recordings: UUIDs in text parts are replaced in the replay key, so agent runs replay on a fresh eval
  database.
- `vat_math` accepts a valid invoice with VAT category O ("not subject to VAT", KoSIT 01.04a): the lines without a
  rate and the breakdown row printing 0 % are one group, and the tax of a category O row must be 0 (a row charging
  tax is still `blocked`). Found by the R3-2 eval; tests for the 01.04a shape and three wrong-math variants.

### Changed
- The eval harness's live spend cap (R4-6): before each live call it keeps the dearest call so far (and at least
  `min_reserve_usd`) free, so the next call cannot overshoot the cap; a live reply without a price is saved and
  stops the run.
- The public demo runs on k3s on the same server since 2026-11-20; Caddy forwards to Traefik instead of a
  Compose container. `make demo-reset` resets the local Compose stack (the demo resets by CronJob).
- The web image no longer ships npm and corepack (the server needs only `node`); the validator's JRE base image
  moved to the current digest (apt CVE-2026-109518 fixed).
- `INVOICEGUARD_EXTRACTION_CONFIDENCE_THRESHOLD` defaults to 0.9 (was 0.8): on the eval set at `low` it flags 5 of 9
  wrong fields (was 1) and 4 of 1,197 right ones (was 2). Replayed from the recordings; `docs/results.md` and
  ADR-010 and ADR-019 updated. The fraud-set numbers in `results.md` are carried over from the earlier run.
- `POST /invoices/{id}/approve` approves `ready` invoices only; a blocked invoice needs the four-eyes override
  (ADR-016), and the R1 field `override_reason` is refused with `422`.
- The Playwright tests run in one worker: the spec files share one stack and the DATEV export.
- `GET /ready` checks the database and returns `503` when it is unreachable.
- The api container applies migrations on start, waits for a healthy `db` and stores uploads in the `uploads` volume.
- uvicorn starts the app through the `create_app` factory (`--factory`), so importing the module does not read settings.
- `POST /invoices` returns `202 Accepted` (was `201`) and schedules processing; invoice responses include `status_reason`.
- The CI smoke test uploads a sample XRechnung, expects `202` and polls until the invoice is `ready`.
- Processed invoices end in `ready` or `blocked` depending on the checks (before: `ready` once read).
- Tests read an invoice after upload by polling until processing has finished, as the UI does.

### Removed
- The Compose deploy path of the demo: `infra/docker-compose.prod.yml`, `make prod-up`, `make prod-down`,
  `make deploy` and `DEPLOY_HOST`; the demo deploys through Argo CD.
