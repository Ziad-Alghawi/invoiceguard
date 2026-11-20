# InvoiceGuard developer commands. Requires GNU make, Docker, uv and pnpm.

# Compose runs from infra/ (see infra/README.md) with the root .env for configuration.
COMPOSE = cd infra && docker compose --env-file ../.env
API = cd apps/api &&
# The eval harness (ADR-019), its own uv project.
EVALS = cd packages/evals &&
WEB = cd apps/web &&
# The read-only MCP servers (ADR-017), each its own uv project.
MCP_SERVERS = apps/mcp-erp apps/mcp-registry apps/mcp-history

# The api tests need INVOICEGUARD_TEST_DATABASE_URL (and INVOICEGUARD_TEST_VALIDATOR_URL for the
# KoSIT tests); read them from the root .env when there is one.
-include .env
export INVOICEGUARD_TEST_DATABASE_URL
export INVOICEGUARD_TEST_VALIDATOR_URL
export INVOICEGUARD_EVAL_DATABASE_URL
export INVOICEGUARD_EVAL_VALIDATOR_URL
# The login users for `make seed-user` (a reviewer and, optionally, an approver for the four-eyes
# override, ADR-016); passed to the one seed command only, never to the running api container.
# `make e2e` logs in with them too.
SEED_VARS = INVOICEGUARD_SEED_USER_EMAIL INVOICEGUARD_SEED_USER_PASSWORD INVOICEGUARD_SEED_USER_NAME 	INVOICEGUARD_SEED_USER_ROLE INVOICEGUARD_SEED_APPROVER_EMAIL INVOICEGUARD_SEED_APPROVER_PASSWORD 	INVOICEGUARD_SEED_APPROVER_NAME
export $(SEED_VARS)
SEED_USER = exec $(foreach var,$(SEED_VARS),-e $(var)) api invoiceguard-seed-user

.PHONY: dev down seed seed-user index check test e2e eval eval-gate demo-reset

dev: ## Build and start api + web + db + validator + MCP servers, wait until all are healthy
ifeq ($(wildcard .env),)
	$(error .env not found: run "cp .env.example .env" first)
endif
	$(COMPOSE) up --build --detach --wait
	@echo "web: http://localhost:3000  api: http://localhost:8000/health"

seed: ## Load the German demo master data into the running stack (safe to run again)
	$(COMPOSE) exec api invoiceguard-seed

seed-user: ## Create or reset the login users from INVOICEGUARD_SEED_USER_* / _APPROVER_* in .env (safe to run again)
	$(COMPOSE) $(SEED_USER)

index: ## (Re)build the booking index and the rulebook: packaged history and vectors, embed the rest with a key
	$(COMPOSE) exec api invoiceguard-index

down: ## Stop and remove the containers (the database volume is kept)
	$(COMPOSE) down

demo-reset: ## Reset the local stack as the demo's nightly CronJob does: invoices, samples, master data, logins
	# As the database owner in a one-off `migrate` container, never as the api's role (ADR-022). The
	# public demo runs the same command as a Kubernetes CronJob (docs/deploy.md).
	$(COMPOSE) run --rm -e INVOICEGUARD_DEMO_MODE=true migrate invoiceguard-demo-reset
	$(COMPOSE) $(SEED_USER)

check: ## Lint, format check and type check (api + web)
	$(API) uv run ruff check
	$(API) uv run ruff format --check
	$(API) uv run mypy
	for dir in $(MCP_SERVERS); do (cd $$dir && uv run ruff check && uv run ruff format --check && uv run mypy) || exit 1; done
	$(EVALS) uv run ruff check && uv run ruff format --check && uv run mypy
	$(WEB) pnpm lint
	$(WEB) pnpm typecheck
	$(WEB) pnpm format:check

test: ## Tests (api + MCP servers + evals + web); the api tests need the db and validator running (make dev)
	$(API) uv run pytest
	for dir in $(MCP_SERVERS); do (cd $$dir && uv run pytest) || exit 1; done
	$(EVALS) uv run pytest
	$(WEB) pnpm test

e2e: ## Playwright browser test against the running stack (make dev, make seed, make seed-user first)
	$(WEB) pnpm exec playwright install chromium
	$(WEB) pnpm e2e

eval: ## Eval harness from the recorded replies (ADR-019), free and offline after the first fetch; needs make dev
	$(EVALS) uv run invoiceguard-eval fetch
	$(EVALS) uv run invoiceguard-eval run --set full

eval-gate: ## The CI eval gate locally: replay the small set, compare with baselines/small.json
	$(EVALS) uv run invoiceguard-eval fetch
	$(EVALS) uv run invoiceguard-eval run --set small
	$(EVALS) uv run invoiceguard-eval gate reports/latest-small.json
