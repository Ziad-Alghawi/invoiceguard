# infra
Deployment and operations config: Docker Compose (dev), Helm chart, Argo CD manifests and Grafana dashboards; Compose in R0, the rest in R4.

## Docker Compose (dev)
[`docker-compose.yml`](docker-compose.yml) runs six services:

| Service | Image | Host port | Healthcheck |
| --- | --- | --- | --- |
| `db` | `pgvector/pgvector:pg16` | `127.0.0.1:5432` | `pg_isready` |
| `api` | built from `apps/api` | `127.0.0.1:8000` | `GET /health` (starts after `db` is healthy) |
| `web` | built from `apps/web` | `127.0.0.1:3000` | `GET /` (starts after `api` is healthy) |
| `validator` | built from `services/validator` (KoSIT, ADR-009) | `127.0.0.1:8081` | `GET /server/health` |
| `mcp-erp` | built from `apps/mcp-erp` (ADR-017) | `127.0.0.1:8091` | TCP port open (starts after `api` is healthy) |
| `mcp-registry` | built from `apps/mcp-registry` (ADR-017) | `127.0.0.1:8092` | TCP port open (starts after `api` is healthy) |

Configuration comes from the root `.env` (copy `.env.example`). Inside the Compose network the web container calls
the API at `http://api:8000`, and the API reaches PostgreSQL at `db:5432` with a URL built from the `POSTGRES_*`
values, and the KoSIT validator at `http://validator:8080/`. The api does not wait for the validator: while it is
down, the KoSIT check is `skipped` and the other checks still run. The one-shot `migrate` service applies pending
Alembic migrations and sets the passwords of the restricted database roles (`invoiceguard-db-roles`) as the
database owner, then exits; the api (as `invoiceguard_app`, ADR-022) and the MCP servers (ADR-017) start after it
and log in with those roles (`INVOICEGUARD_APP_DB_PASSWORD` and `INVOICEGUARD_MCP_*_DB_PASSWORD`, required).
`make demo-reset` runs in a one-off `migrate` container too: owner tasks never run as the api's role. Database data is kept in the `db-data` volume, uploaded invoice files in the
`uploads` volume (mounted at `/data/uploads`).

`make seed` loads the demo master data into the running stack (`docker compose exec api invoiceguard-seed`).

Use `make dev` / `make down` from the repo root. Without make:

```sh
cd infra
docker compose --env-file ../.env up --build --detach --wait
docker compose --env-file ../.env down
```

Run Compose from this folder, not with `-f infra/docker-compose.yml` from the root: on Docker Desktop for Windows,
Compose v5 builds through Bake, which refuses to read the build contexts in `apps/` from the root
(`additional privileges requested: pass "--allow=fs.read=..."`).

Both images are multi-stage and run as non-root users. The web image uses Next.js `output: "standalone"` and reads
`API_URL` at runtime, so one image works in every environment.

## Helm (Kubernetes, R4-3)
Two charts ([ADR-023](../docs/decisions/ADR-023-helm-chart-and-postgres.md)); install them in this order:

- [`helm/invoiceguard-postgres`](helm/invoiceguard-postgres): PostgreSQL 16 with pgvector, a StatefulSet
  with a local volume. On its first start an init script creates the non-superuser owner, its database and
  the extensions.
- [`helm/invoiceguard`](helm/invoiceguard): api, web, validator, `mcp-erp`, `mcp-registry`, `mcp-history`,
  the migration hook and the demo-reset CronJob, plus the Traefik ingress with a body-size limit and the
  NetworkPolicies. The images come from GHCR by commit SHA (`image.tag`, required).

Secrets are referenced by name only. The install steps, the secret keys and the local k3d test are in
[`docs/deploy.md`](../docs/deploy.md#5-test-the-charts-locally-on-k3d). CI lints, renders and installs both charts on
k3d (job `helm`).

## k3s and Argo CD (R4-4)
The demo server runs one k3s node ([ADR-021](../docs/decisions/ADR-021-platform-k3s-argocd.md)):

- [`k3s/`](k3s): the server's k3s settings (no ServiceLB, encrypted Secrets), Traefik's settings (a
  hostPort 8880 that the shared Caddy reaches through Docker's bridge, trusted forwarded headers), a systemd drop-in
  that starts k3s after Docker, `fetch.sh` (Argo CD core, the sealed-secrets controller and kubeseal at
  pinned versions, checked by SHA-256) and `seal-secrets.sh`.
- [`argocd/`](argocd): the root Application (app-of-apps) and, in [`argocd/apps/`](argocd/apps), the
  namespace, the SealedSecrets and the three chart Applications in sync waves (PostgreSQL first, monitoring last). Argo CD
  follows the git tag `demo`, which CI moves after a `main` commit's images are in GHCR.
  [`argocd/bootstrap/`](argocd/bootstrap) holds what the core install lacks: the `default` project, a health
  check for child Applications and a repo-server that renders one chart at a time.

CI (job `helm`) checks the pinned hashes, dry-runs these manifests, lets Argo CD core bootstrap and render the
Applications at the commit, and starts k3s's Traefik with the server's settings, all on k3d. The steps on the
server are in [`docs/deploy.md`](../docs/deploy.md) ([ADR-024](../docs/decisions/ADR-024-edge-and-cluster-bootstrap.md)).

## Metrics (R4-5)
[ADR-025](../docs/decisions/ADR-025-metrics-prometheus-local-grafana.md):

- [`helm/invoiceguard-monitoring`](helm/invoiceguard-monitoring): Prometheus alone. It scrapes the api's
  `/metrics` (every api pod, through the app chart's headless Service), keeps 7 days and evaluates the alert
  rules in [`files/rules.yml`](helm/invoiceguard-monitoring/files/rules.yml), whose promtool unit tests are in
  [`tests/`](helm/invoiceguard-monitoring/tests). It has no Ingress.
- [`grafana/`](grafana): Grafana for the developer machine (`make grafana`, http://localhost:3001), with the
  Prometheus datasource and the **InvoiceGuard** dashboard provisioned. It reads the demo's Prometheus through
  an SSH tunnel ([`docs/deploy.md`](../docs/deploy.md#metrics)).

## The server's edge
[`edge/`](edge) is the server's shared reverse proxy, not part of this project's stack: one Caddy with ports
80/443 and automatic Let's Encrypt certificates, shared security headers, and one file per site in
[`edge/sites/`](edge/sites). It is copied to `/opt/edge` on the server, so other projects can add their sites.
