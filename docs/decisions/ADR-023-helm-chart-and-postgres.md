# ADR-023: Helm chart, a separate PostgreSQL chart and a non-superuser owner

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

ADR-021 moves the demo to k3s with one node, deployed from a Helm chart in the repo. ADR-022 runs the
migrations as a separate step with the database owner, before the api and the MCP servers start. In
Kubernetes that step is a Job that runs before each release: a Helm `pre-install`/`pre-upgrade` hook,
which Argo CD runs as PreSync.

Forces:

- **Hook order:** Helm runs a `pre-install` hook before it creates anything else in the same release.
  If PostgreSQL were in the release, even as a subchart, the first install's migration Job would wait
  for a database that does not exist yet.
- **One 8 GB node** (ADR-021), shared with k3s, Argo CD and Prometheus/Grafana (R4-5).
- **The superuser migrator** (known limitation in ADR-022): the owner is `POSTGRES_USER`, a superuser in the
  official image. The migrations create roles (ADR-017, ADR-022) and the `vector` extension, which is not a
  trusted extension and needs a superuser.
- **Images:** Kubernetes can check `runAsNonRoot` only for a numeric user; the images named theirs
  (`USER app`).

## Decision

- **Two charts.** `infra/helm/invoiceguard-postgres` runs PostgreSQL 16 with pgvector: one StatefulSet with
  a local volume, the image pinned by digest, no backups (sample data, reset nightly; ADR-021). It is
  installed first. `infra/helm/invoiceguard` holds the api, web, the KoSIT validator, the three MCP servers,
  the migration hook and the demo-reset CronJob, with the images by commit SHA (`image.tag` is required).
  In R4-4 they become two Argo CD Applications in sync waves.
- **A non-superuser owner.** On its first start (empty volume) the postgres chart runs one init script as
  the superuser. It creates `invoiceguard_owner` with `LOGIN NOSUPERUSER NOCREATEDB CREATEROLE`, the
  `invoiceguard` database owned by it, and the `vector` and `pg_trgm` extensions. The migrations' `CREATE
  EXTENSION IF NOT EXISTS` then finds them. In PostgreSQL 16, `CREATEROLE` lets the owner manage only the
  roles it created itself. The migration hook and the demo reset log in as the owner. The superuser's
  password is used only inside the postgres pod.
- **Migrations as a hook.** A `pre-install,pre-upgrade` Job runs `alembic upgrade head &&
  invoiceguard-db-roles` as the owner, after an init container has waited for the database. Hooks run before
  the release's other objects exist, so the Job sets everything it needs itself (no chart ConfigMap or
  ServiceAccount). A Job that succeeded is deleted; a failed one stays for its logs.
- **Secrets by name only:** `invoiceguard-postgres` (superuser and owner passwords) and `invoiceguard`
  (the restricted roles' passwords, the demo logins, an optional model key) are created outside the charts;
  sealed-secrets follows in R4-4. The database URLs are put together in the pod from the password variable.
- **Pods:**
  - Every pod runs as a numeric non-root user (999, or 1000 for web), with a read-only root filesystem
    (an `emptyDir` for `/tmp` and the Next.js cache), no privilege escalation, no capabilities, the
    RuntimeDefault seccomp profile and no ServiceAccount token.
  - Service links are off: a Service called `invoiceguard-api` would otherwise set `INVOICEGUARD_API_PORT`,
    which the `INVOICEGUARD_` settings would read.
  - The Dockerfiles name the same IDs (`USER 999:999`), so the Compose volumes keep their owner.
- **NetworkPolicies:**
  - Incoming traffic is denied unless allowed: Traefik reaches web, web reaches the api, and the api
    reaches the MCP servers and the validator.
  - Only pods labelled `invoiceguard.io/database-client` reach PostgreSQL: the api, the MCP servers, the
    migration hook and the demo reset.
  - Outgoing traffic is limited for web (api and DNS), the MCP servers (database and DNS) and the
    validator (nothing). The api keeps open outgoing traffic for the model APIs.
- **Ingress:** Traefik routes to web only. A Traefik `buffering` middleware refuses bodies above 11 MiB
  (the 10 MiB upload limit plus multipart overhead) with 413.
- **Sizing:** memory requests of about 1.2 GB in total, a little above what the pods used idle on k3d
  (the validator about 430 MiB, the api about 140 MiB, the others under 75 MiB each). Each pod has a
  memory limit. CPU has requests but no limits, so a busy pod is not throttled while the node has spare
  CPU.
- **Tested on k3d in CI:** both charts are installed on k3d (k3s, with the same Traefik, local-path storage
  and NetworkPolicy enforcement as the server). The smoke test checks login, the demo reset, the 413 limit
  and the NetworkPolicies.

## Alternatives

- **PostgreSQL as a subchart or in the same chart:** one install, but the migration hook runs before
  the database exists on a first install.
- **Migrations as a plain Job, without hooks, and init containers that wait for the schema:** one chart,
  but a Job's spec cannot change, so each release needs a new Job name. Old Jobs pile up, and the pods
  would have to check the schema version themselves.
- **Bitnami PostgreSQL chart:** well known, but its free images moved to a paid catalogue in 2025.
- **CloudNativePG:** a real operator with failover and backups, but an operator, CRDs and a few hundred
  MB of memory for one instance on one node.
- **kind instead of k3d for the CI test:** standard, but without Traefik, local-path storage or a
  NetworkPolicy controller, so the ingress and the policies would go untested.
- **Keep the superuser migrator:** nothing to change, but the owner could then create extensions and
  roles of any kind.

## Consequences

- Two installs in a fixed order. Changing the init script does not touch an existing database (it runs on
  an empty volume only); the owner, its database and the extensions are set up once.
- The migrations need no superuser in Kubernetes. A future migration that needs one (a new untrusted
  extension) has to go into the init script and onto the existing database by hand.
- Compose keeps the superuser migrator until R4-4 switches it off: changing the owner of the live demo
  database is not worth it for a few weeks.
- The uploads volume is ReadWriteOnce: the api pods and the demo reset must run on one node, which holds
  for the one-node demo. More nodes need a ReadWriteMany volume or object storage.
- R4-4: k3s's Traefik must trust `X-Forwarded-For` from Caddy (`trustedIPs` on its entry point). Otherwise
  it replaces the header with Caddy's address, and the per-IP login limit counts every visitor as one
  address. The api trusts the pod network (`podCidr`), that is the web pods.
- Amends ADR-021 (migrations run as a Helm hook, which Argo CD runs as PreSync; PostgreSQL in its own chart)
  and ADR-022 (the migrator is no superuser in Kubernetes).
