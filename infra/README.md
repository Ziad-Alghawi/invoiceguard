# infra
Deployment and operations config: Docker Compose (dev), Helm chart, Argo CD manifests and Grafana dashboards; Compose in R0, the rest in R4.

## Docker Compose (dev)
[`docker-compose.yml`](docker-compose.yml) runs four services:

| Service | Image | Host port | Healthcheck |
| --- | --- | --- | --- |
| `db` | `pgvector/pgvector:pg16` | `127.0.0.1:5432` | `pg_isready` |
| `api` | built from `apps/api` | `127.0.0.1:8000` | `GET /health` (starts after `db` is healthy) |
| `web` | built from `apps/web` | `127.0.0.1:3000` | `GET /` (starts after `api` is healthy) |
| `validator` | built from `services/validator` (KoSIT, ADR-009) | `127.0.0.1:8081` | `GET /server/health` |

Configuration comes from the root `.env` (copy `.env.example`). Inside the Compose network the web container calls
the API at `http://api:8000`, and the API reaches PostgreSQL at `db:5432` with a URL built from the `POSTGRES_*`
values, and the KoSIT validator at `http://validator:8080/`. The api does not wait for the validator: while it is
down, the KoSIT check is `skipped` and the other checks still run. The api container applies pending Alembic
migrations before it starts serving. Database data is kept in the `db-data` volume, uploaded invoice files in the
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
