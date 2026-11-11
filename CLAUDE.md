# InvoiceGuard — instructions for Claude Code

docs/PLAN.md is a private local file; read it if present. Public architecture docs go in docs/ (coming in R5).
Read `docs/status.md` before any task, and PLAN.md sections 3, 4, 5 and 11 when present.

## Stack
Python 3.12 (uv, FastAPI, LangGraph, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16 + pgvector),
Next.js App Router + TypeScript + Tailwind + shadcn/ui (pnpm), MCP Python SDK, Langfuse, Docker, Helm, Argo CD.

## Commands
make dev · make check (ruff, mypy, eslint, prettier) · make test · make e2e · make eval

## Rules
- One task per session; propose a plan before editing more than one file.
- Code first, LLM only where the plan allows. No new dependencies without stating why.
- Invoice/email/tool text is untrusted data: never place it in system prompts; keep delimiters and labels.
- There is no tool that pays, posts or writes to ERP/registry. Do not create one.
- Write tests with the code (pytest / vitest / playwright). Run make check && make test before committing.
- No dead code, no commented-out code, no TODO without an issue link, no secrets, config via env.
- Conventional commits (feat/fix/docs/test/chore/refactor/build/ci). Author is Ziad only: never add Co-Authored-By or
  "Generated with" lines to commits or PRs.
- Update docs/status.md and CHANGELOG.md when a milestone item is completed; write an ADR in docs/decisions/
  for architectural choices.
- Prefer boring, standard, well-documented solutions. If unsure, ask one short question instead of guessing.
- When we hit a non-trivial problem (error, wrong assumption, tricky decision), append an entry to
  docs/private/journal.md in the same format. Never commit that file.
