# apps/api
Python 3.12 FastAPI backend with the LangGraph pipeline (ingest, parse, check, propose, human approval, export); filled from R1.

## Run
```sh
uv sync
uv run uvicorn invoiceguard_api.main:app --reload
```

Endpoints so far: `GET /health` (liveness) and `GET /ready` (readiness). Logs are JSON, one object per line.

## Configuration
Settings are read from environment variables prefixed with `INVOICEGUARD_` (see the root `.env.example`).
Invalid values stop the app at startup.

| Variable | Values | Default |
| --- | --- | --- |
| `INVOICEGUARD_ENV` | `dev`, `test`, `prod` | `dev` |
| `INVOICEGUARD_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO` |

## Checks
```sh
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

## Docker
The [Dockerfile](Dockerfile) installs the locked runtime dependencies with uv in a build stage and copies only the
virtual environment into a `python:3.12-slim` image that runs as a non-root user on port 8000. The whole stack
(api + web + db) starts with `make dev` from the repo root; see [infra](../../infra/README.md).
