# InvoiceGuard

[![CI](https://github.com/Ziad-Alghawi/invoiceguard/actions/workflows/ci.yml/badge.svg)](https://github.com/Ziad-Alghawi/invoiceguard/actions/workflows/ci.yml)

Agentic platform for incoming supplier invoices (XRechnung, ZUGFeRD, PDF): it reads them, checks them against rules and master data, catches fraud and prompt-injection attacks, prepares the booking, and lets a human approve. The agent can never pay or post anything on its own.

> Status: R0 (foundation) done, R1 (working core) next. Sections below are filled as each release lands.

## Problem

_Coming in R1._

## Demo

_Coming in R1 (live link), GIF in R5._

## Architecture

_Coming in R5 (diagram). Monorepo layout: `apps/`, `services/`, `packages/`, `infra/`, `workflows/`, `docs/`._

## How it works

_Coming in R1._

## Safety design

_Coming in R2 (approval gate, read-only tools, injection boundaries, OWASP Agentic Top 10 mapping)._

## Results

_Coming in R3 (field accuracy, fraud recall, attack success rate, cost per invoice, p95 latency)._

## Model comparison

_Coming in R4._

## Run locally

Requires Docker and GNU make (on Windows: `scoop install make` or `winget install ezwinports.make`).

```sh
git clone https://github.com/Ziad-Alghawi/invoiceguard.git && cd invoiceguard
cp .env.example .env
make dev        # api + web + db, waits until all are healthy
```

Open http://localhost:3000: the page shows `API: ok`. `make down` stops the stack.

For development without Docker you also need [uv](https://docs.astral.sh/uv/) and Node.js 24 with pnpm
(see [apps/api](apps/api/README.md) and [apps/web](apps/web/README.md)):

| Command | What it runs |
| --- | --- |
| `make check` | ruff, ruff format, mypy, eslint, tsc, prettier |
| `make test` | pytest, vitest |
| `make eval` | evaluation harness (R3) |
| `uvx pre-commit install` | git hooks: ruff, prettier, whitespace, large files, detect-secrets |

## Decisions

Architectural choices are recorded as ADRs in [docs/decisions](docs/decisions/README.md):

- [ADR-001: Technology stack](docs/decisions/ADR-001-stack.md)
- [ADR-002: Boundary between deterministic code and LLMs](docs/decisions/ADR-002-code-vs-llm-boundary.md)
- [ADR-003: Human approval is a hard gate](docs/decisions/ADR-003-approval-hard-gate.md)

## Roadmap

- R0 Foundation: repo, tooling, CI, Docker Compose
- R1 Working core: parsing, validation, checks, review queue, CSV export, live demo
- R2 Agent, MCP servers, approval gate, injection defence
- R3 Evals, RAG booking suggestions, CI quality gate
- R4 Platform: Helm, Argo CD, observability, model router, n8n
- R5 Polish: German UI, README EN + DE, demo video

## Limitations

_Coming in R1._

## Deutsch

_Kommt in R5._

## License

[MIT](LICENSE)
