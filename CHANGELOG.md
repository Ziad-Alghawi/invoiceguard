# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Monorepo skeleton (`apps/`, `services/`, `packages/`, `infra/`, `workflows/`, `docs/decisions/`) with a purpose README per folder.
- MIT licence, README skeleton, `CLAUDE.md`, `docs/status.md`, `.gitignore`, `.env.example`, `.editorconfig`.
- ADR template and ADR-001 (stack), ADR-002 (code vs LLM boundary), ADR-003 (approval as hard gate), linked from the README.
- `apps/api` uv project (Python 3.12, FastAPI) with `GET /health` and `GET /ready`, env-based settings (pydantic-settings), JSON logging, and ruff, mypy (strict) and pytest with coverage.
- `apps/web` pnpm project (Next.js App Router, TypeScript strict, Tailwind, shadcn/ui) with a home page that shows the API `GET /health` status (`ok` / `unreachable`) from `NEXT_PUBLIC_API_URL`, and eslint, prettier and vitest.
