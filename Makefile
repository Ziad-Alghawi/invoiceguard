# InvoiceGuard developer commands. Requires GNU make, Docker, uv and pnpm.

# Compose runs from infra/ (see infra/README.md) with the root .env for configuration.
COMPOSE = cd infra && docker compose --env-file ../.env
# The public demo (ADR-014, docs/deploy.md): the dev stack plus the prod override, behind the
# server's shared Caddy (infra/edge).
PROD = $(COMPOSE) -f docker-compose.yml -f docker-compose.prod.yml
API = cd apps/api &&
WEB = cd apps/web &&

# The api tests need INVOICEGUARD_TEST_DATABASE_URL (and INVOICEGUARD_TEST_VALIDATOR_URL for the
# KoSIT tests); read them from the root .env when there is one.
-include .env
export INVOICEGUARD_TEST_DATABASE_URL
export INVOICEGUARD_TEST_VALIDATOR_URL
# The login user for `make seed-user`; passed to the one seed command only, never to the
# running api container.
export INVOICEGUARD_SEED_USER_EMAIL
export INVOICEGUARD_SEED_USER_PASSWORD
export INVOICEGUARD_SEED_USER_NAME

.PHONY: dev down seed seed-user check test e2e eval prod-up prod-down demo-reset deploy

dev: ## Build and start api + web + db + validator, wait until all are healthy
ifeq ($(wildcard .env),)
	$(error .env not found: run "cp .env.example .env" first)
endif
	$(COMPOSE) up --build --detach --wait
	@echo "web: http://localhost:3000  api: http://localhost:8000/health"

seed: ## Load the German demo master data into the running stack (safe to run again)
	$(COMPOSE) exec api invoiceguard-seed

seed-user: ## Create or reset the login user from INVOICEGUARD_SEED_USER_* in .env (safe to run again)
	$(COMPOSE) exec -e INVOICEGUARD_SEED_USER_EMAIL -e INVOICEGUARD_SEED_USER_PASSWORD 		-e INVOICEGUARD_SEED_USER_NAME api invoiceguard-seed-user

down: ## Stop and remove the containers (the database volume is kept)
	$(COMPOSE) down

prod-up: ## Demo server: build and start the stack on the `edge` network, wait until healthy
ifeq ($(wildcard .env),)
	$(error .env not found: see docs/deploy.md)
endif
	$(PROD) up --build --detach --wait --remove-orphans

prod-down: ## Demo server: stop the stack (volumes with data are kept)
	$(PROD) down

demo-reset: ## Demo server: delete all invoices, reload the samples, reset the demo login
	$(PROD) exec api invoiceguard-demo-reset
	$(PROD) exec -e INVOICEGUARD_SEED_USER_EMAIL -e INVOICEGUARD_SEED_USER_PASSWORD 		-e INVOICEGUARD_SEED_USER_NAME api invoiceguard-seed-user

deploy: ## From your machine: pull and restart the demo over SSH (DEPLOY_HOST in .env, docs/deploy.md)
ifeq ($(strip $(DEPLOY_HOST)),)
	$(error DEPLOY_HOST is empty: set it in .env, for example DEPLOY_HOST=deploy@<server IP> (see docs/deploy.md, section 6))
endif
	ssh $(DEPLOY_HOST) "cd /opt/invoiceguard && git pull && make prod-up"

check: ## Lint, format check and type check (api + web)
	$(API) uv run ruff check
	$(API) uv run ruff format --check
	$(API) uv run mypy
	$(WEB) pnpm lint
	$(WEB) pnpm typecheck
	$(WEB) pnpm format:check

test: ## Tests (api + web); the api tests need the db and validator running (make dev)
	$(API) uv run pytest
	$(WEB) pnpm test

e2e: ## Playwright browser test against the running stack (make dev, make seed, make seed-user first)
	$(WEB) pnpm exec playwright install chromium
	$(WEB) pnpm e2e

eval: ## Evaluation harness
	@echo "make eval: not implemented yet (R3)"
