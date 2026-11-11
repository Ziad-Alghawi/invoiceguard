# InvoiceGuard

Agentic platform for incoming supplier invoices (XRechnung, ZUGFeRD, PDF): it reads them, checks them against rules and master data, catches fraud and prompt-injection attacks, prepares the booking, and lets a human approve. The agent can never pay or post anything on its own.

> Status: R0 (foundation) in progress. Sections below are filled as each release lands.

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

_Coming in R0 (three commands with Docker Compose)._

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
