# Contributing

InvoiceGuard is a single-author portfolio project, but issues and small pull requests are welcome. Please open
an issue first for anything larger than a fix, so we can agree on the approach before you write code.

## Set up

Follow [Run locally](README.md#run-locally): Docker and GNU make for the stack, plus
[uv](https://docs.astral.sh/uv/) and Node.js 24 with pnpm to work outside the containers. Install the git hooks
with `uvx pre-commit install`.

## Rules

- **One task per pull request**, with tests written together with the code (pytest, Vitest, Playwright).
- **Run `make check` and `make test` before you push**, and `make e2e` when UI text or an output format changes.
- **Code first, LLM only where code cannot do the job** ([ADR-002](docs/decisions/ADR-002-code-vs-llm-boundary.md)).
- **Invoice, email and tool text is untrusted data:** never put it into a system prompt; keep the labelled
  delimiters.
- **No tool that pays, posts or writes to an ERP or registry.** Such a pull request will not be merged.
- **No dead or commented-out code, no TODO without an issue link, no secrets;** configuration through the
  environment (`.env.example`).
- **No new dependency without saying why,** and only releases that have been public for at least a week
  ([ADR-004](docs/decisions/ADR-004-model-router.md)).
- **UI text goes into `apps/web/messages/de.json` and `en.json`,** never into a component
  ([ADR-027](docs/decisions/ADR-027-ui-languages.md)).
- **Architectural choices get an ADR** in [docs/decisions](docs/decisions/README.md), from the template.
- **Conventional commits:** `feat`, `fix`, `docs`, `test`, `chore`, `refactor`, `build`, `ci`.

## Pull requests

Fill in the template: what changes, why, and how it was tested. CI must be green (lint, types, tests, the
Playwright tests on Docker Compose, the Helm install on k3d, the image scan and, when relevant, the eval gate).

Security problems go to [SECURITY.md](SECURITY.md), not to a public issue.
