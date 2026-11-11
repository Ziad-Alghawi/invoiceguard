# ADR-001: Technology stack

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

InvoiceGuard reads incoming supplier invoices (XRechnung, ZUGFeRD, PDF), checks them, prepares a
booking and puts them in front of a human for approval. It needs an API with strict data validation, an
agent runtime that can pause for a human, a relational database with vector search, a review UI, and a
reproducible way to deploy. It is built by one developer, so the stack must be standard, well documented
and free to run.

## Decision

| Area | Choice | Why |
| --- | --- | --- |
| Language (backend) | Python 3.12 | Best ecosystem for XML, PDF and LLM work; typed with mypy. |
| Packaging | uv | Fast, lockfile-based, one tool for Python versions and dependencies. |
| API | FastAPI | Async, OpenAPI out of the box, built on Pydantic. |
| Validation | Pydantic v2 | One schema type for API payloads, LLM structured output and internal models. |
| Agent runtime | LangGraph | Explicit graph, `interrupt()` for human approval, durable checkpoints. |
| Database | PostgreSQL 16 + pgvector | One database for business data, agent checkpoints and embeddings. |
| ORM / migrations | SQLAlchemy 2 + Alembic | Mature, typed, the default choice in Python. |
| Tool protocol | MCP Python SDK | Standard way to expose read-only data sources to the agent with clear boundaries. |
| Frontend | Next.js App Router + TypeScript | Mainstream React framework with server components and routing. |
| UI | Tailwind + shadcn/ui | Accessible components we own as code, no heavy UI library. |
| JS packages | pnpm | Fast, strict about undeclared dependencies. |
| Tracing | Langfuse | Open-source LLM tracing with cost and latency per call; self-hostable. |
| Packaging / deploy | Docker, Helm, Argo CD | Containers for every service, Helm for Kubernetes, GitOps so `main` is what runs. |

Choices that need a short experiment first (model-router library, ZUGFeRD reader library) get their
own ADRs.

## Alternatives

- **Node.js / TypeScript backend:** weaker XML-validation and PDF tooling; Python is the norm for LLM work.
- **Poetry or pip-tools:** slower and more moving parts than uv.
- **Django:** more than we need; FastAPI fits a JSON API with Pydantic schemas.
- **Plain LangChain agents / custom loop:** no built-in, durable human-in-the-loop pause.
- **Separate vector database (Qdrant, Pinecone):** another service to run; pgvector is enough at this scale.
- **Raw SQL or SQLModel:** less mature migrations and typing than SQLAlchemy 2 + Alembic.
- **Custom tool interface instead of MCP:** works, but not a standard and harder to reuse or audit.
- **Vite SPA:** fine, but Next.js gives routing and server rendering without extra setup.
- **MUI / Chakra:** larger runtime, harder to customise than shadcn/ui.
- **LangSmith:** hosted and paid beyond the free tier; Langfuse can be self-hosted.
- **Docker Compose only / plain kubectl:** no reproducible path to a real cluster with drift detection.

## Consequences

- Two languages (Python and TypeScript) to maintain, each with its own lint, type and test tools.
- PostgreSQL is a single critical dependency; we accept that for simpler operations.
- LangGraph and MCP are young and change quickly; we pin versions and keep agent code behind small
  interfaces so upgrades stay contained.
- Kubernetes, Helm and Argo CD add operational weight; local development stays on Docker Compose.
