# Nexiqon developer commands. `make help` lists them.
SHELL := /bin/bash
COMPOSE := docker compose -f deploy/compose/docker-compose.yml
PROFILES ?=
PNPM := npx --yes pnpm@12.15.0 --dir frontend
comma := ,
PROFILE_FLAGS := $(foreach p,$(subst $(comma), ,$(PROFILES)),--profile $(p))

.PHONY: studio dev-secrets help setup lint format typecheck test test-unit arch contracts contracts-check \
        fe-install fe-lint fe-test fe-build check new-service dev-up dev-down dev-logs run-group image

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

setup: ## Install Python + frontend deps and git hooks
	uv sync --all-packages
	$(PNPM) install
	uv run pre-commit install

lint: ## Ruff lint + format check
	uv run ruff check .
	uv run ruff format --check .

format: ## Auto-format Python
	uv run ruff format .
	uv run ruff check --fix .

typecheck: ## mypy (strict) on libs and services
	uv run mypy libs/nexiqon-core/src services/*/src

arch: ## Architecture rules: vendor SDKs behind adapters, no domain words in core
	uv run python tools/lint/check_architecture.py

test: ## All Python tests (integration tests need Docker)
	uv run pytest

test-unit: ## Python tests without Docker
	uv run pytest -m "not integration"

contracts: ## Export OpenAPI contracts and regenerate TS types
	uv run python -m tools.contracts.export_openapi
	$(PNPM) generate

contracts-check: ## Fail if contracts are stale
	uv run python -m tools.contracts.export_openapi --check

fe-install: ## Install frontend deps
	$(PNPM) install

fe-lint: ## Frontend lint + typecheck
	$(PNPM) lint
	$(PNPM) typecheck

fe-test: ## Frontend tests
	$(PNPM) test

fe-build: ## Build Studio and widget
	$(PNPM) build

check: lint typecheck arch contracts-check test fe-lint fe-test ## Everything CI runs

new-service: ## Generate a service: make new-service NAME=foo PLANE=data
	@test -n "$(NAME)" -a -n "$(PLANE)" || (echo "usage: make new-service NAME=<kebab> PLANE=<control|data>"; exit 1)
	uv run copier copy --defaults --data service_name=$(NAME) --data plane=$(PLANE) templates/service services/$(NAME)
	uv sync --all-packages
	@echo "Now add '$(NAME)' to a group in deploy/groups.yaml and run 'make contracts'."

dev-secrets: ## Generate local signing keys (deploy/compose/config/dev-secrets.yaml, git-ignored)
	uv run python tools/dev/gen_dev_secrets.py

dev-up: dev-secrets ## Start local stack (PROFILES=platform,apps,observability,scan,models)
	NEXIQON_TELEMETRY=$(if $(findstring observability,$(PROFILES)),true,false) $(COMPOSE) $(PROFILE_FLAGS) up -d --build

dev-down: ## Stop local stack (all profiles)
	$(COMPOSE) --profile '*' down

dev-logs: ## Follow logs
	$(COMPOSE) $(PROFILE_FLAGS) logs -f

run-group: ## Run a group locally without Docker: make run-group GROUP=control-core
	uv run nexiqon-run --group $(GROUP) --port $${PORT:-8000}

studio: ## Run Studio (admin UI) on :3100 against the local stack (needs make dev-up PROFILES=platform,apps)
	npx --yes pnpm@12.15.0 --dir frontend/apps/studio exec next dev --port 3100

image: ## Build the platform image
	docker build -f deploy/docker/Dockerfile -t nexiqon/platform:dev .
