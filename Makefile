# InvoiceGuard developer commands. Requires GNU make, Docker, uv and pnpm.

# Compose runs from infra/ (see infra/README.md) with the root .env for configuration.
COMPOSE = cd infra && docker compose --env-file ../.env
API = cd apps/api &&
WEB = cd apps/web &&

# The api tests need INVOICEGUARD_TEST_DATABASE_URL; read it from the root .env when there is one.
-include .env
export INVOICEGUARD_TEST_DATABASE_URL

.PHONY: dev down seed check test eval

dev: ## Build and start api + web + db, wait until all are healthy
ifeq ($(wildcard .env),)
	$(error .env not found: run "cp .env.example .env" first)
endif
	$(COMPOSE) up --build --detach --wait
	@echo "web: http://localhost:3000  api: http://localhost:8000/health"

seed: ## Load the German demo master data into the running stack (safe to run again)
	$(COMPOSE) exec api invoiceguard-seed

down: ## Stop and remove the containers (the database volume is kept)
	$(COMPOSE) down

check: ## Lint, format check and type check (api + web)
	$(API) uv run ruff check
	$(API) uv run ruff format --check
	$(API) uv run mypy
	$(WEB) pnpm lint
	$(WEB) pnpm typecheck
	$(WEB) pnpm format:check

test: ## Tests (api + web); the api tests need the db running (make dev)
	$(API) uv run pytest
	$(WEB) pnpm test

eval: ## Evaluation harness
	@echo "make eval: not implemented yet (R3)"
