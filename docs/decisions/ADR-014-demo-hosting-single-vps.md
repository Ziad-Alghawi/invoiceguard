# ADR-014: R1 demo on one VPS with Docker Compose and Caddy

- **Status:** Accepted
- **Date:** 2026-11-14 (updated 2026-11-18 with R2-7: upload page, demo upload rules)

## Context

R1 ends with a public demo: a recruiter or reviewer opens a link, logs in with a shared account (ADR-006) and
works through a review queue. The plan put the demo on a Kubernetes cluster, but Helm, Argo CD and the cluster
come in R4, and they are out of scope for R1.

The stack has four containers: PostgreSQL with pgvector, the API, the KoSIT validator (a JVM that needs about
0.5 to 1 GB of memory) and the web app. The API processes invoices inside its own process (ADR-007), so it must
not sleep between requests. Uploaded files need a persistent disk. Session cookies are `Secure` in production
(ADR-011), so the demo needs HTTPS. Budget: free or nearly free, and at most €20 for LLM calls over the whole
project.

## Decision

Run the R1 demo on **one Hetzner Cloud VPS** (2 vCPU, 4 GB RAM, in Germany) with the **same Docker Compose
stack** we test in CI, plus a production override (`infra/docker-compose.prod.yml`):

- **One shared Caddy** for the whole server (`infra/edge`, copied to `/opt/edge`), because more small projects
  will run on the same VPS. It is the only container with public ports (80, 443), gets and renews a Let's Encrypt
  certificate for every site (here `invoiceguard.ziadalghawi.com`, a DNS A record at the registrar), redirects
  HTTP to HTTPS and sets shared security headers. Each project puts one file into `sites/` and attaches its public
  container to the Docker network `edge` under a unique alias (`invoiceguard-web`). The API, validator and
  database have no published ports and are not on `edge`; the browser talks only to the web server, which calls
  the API over the project's own network (backend for frontend).
- `INVOICEGUARD_ENV=prod` makes the session cookie `Secure`. Secrets live only in the server's `.env` (mode
  600), never in git.
- **Demo safety:** a daily LLM spending cap (`INVOICEGUARD_LLM_DAILY_BUDGET_USD`, default 0.50 in the override)
  summed from `model_calls`; once reached, PDFs wait in `awaiting_extraction`. The web app has no upload page and
  the API is not public, so visitors cannot upload at all in R1; the cap is the backstop for when that changes.
- **Demo uploads (R2-7):** the web app has an upload page now (through the web server, the API stays private). With
  `INVOICEGUARD_DEMO_MODE=true` the API refuses a PDF without embedded e-invoice XML (`422` with a clear message,
  nothing stored), so no visitor's PDF is sent to a model, even if a key is ever set (ADR-010 data protection).
  XRechnung XML and ZUGFeRD / Factur-X PDFs are processed by code only. Limits: 10 MiB per file (API) and 12 MB per
  request (Caddy), and `INVOICEGUARD_UPLOAD_MAX_PER_HOUR` uploads per user (default 30 in the override; `429`),
  counted from the audit log. The demo accounts are shared, so the hourly limit caps all visitors together. Uploaded
  invoices are deleted with everything else by the nightly reset.
- **Demo data:** `make demo-reset` (only with `INVOICEGUARD_DEMO_MODE=true`) deletes all invoices, exports and
  files, restores the master data, loads five sample invoices and resets the demo login. A nightly cron job runs
  it. The audit log stays append-only: the reset is recorded as an event, earlier events are kept.
- Images are built on the server from the git checkout (`git pull && make prod-up`); migrations run when the API
  starts.
- The server's firewall is a **Hetzner Cloud Firewall** (22, 80, 443), outside the VM: ports that Docker
  publishes bypass `ufw` rules on the host.

## Alternatives

- **Free PaaS tiers split across providers** (Vercel for the web app, Render or Fly for the API and validator,
  Neon for Postgres): €0 only while services may sleep, which stops in-process background work and makes the
  first visit wait about a minute; uploads need object storage; three or four dashboards for config and secrets;
  the deployment differs from the stack we test. Kept services always on, it costs more than the VPS.
- **Oracle Cloud Always Free (ARM)**: €0 and the same Compose setup, but sign-up and capacity are unreliable,
  idle instances can be reclaimed, and every image must be built for ARM. Too fragile for a link on a CV.
- **Kubernetes now** (as in the plan): the right target for R4, but it would pull Helm, Argo CD and secret
  management into R1.

## Consequences

- About €5 a month; nothing sleeps; the demo runs the exact images and Compose file CI tests.
- One server is a single point of failure, and we patch the OS (unattended upgrades, SSH keys only). No
  backups: the demo data is reset every night anyway.
- One API process stays a requirement (ADR-007); a single VPS fits it.
- The shared demo password is public on the login page, so anyone can lock the demo account for 15 minutes with
  wrong passwords (ADR-011); the nightly reset unlocks it, and a per-IP rate limit comes with the ingress in R4.
- Adding a site is a file and a reload, without touching InvoiceGuard; a broken site file stops Caddy's reload
  for all sites, so `caddy validate` runs first (CI validates ours).
- In R4 the same images move to the cluster; Caddy's job goes to the ingress controller and cert-manager, the
  reset becomes a Kubernetes CronJob.
