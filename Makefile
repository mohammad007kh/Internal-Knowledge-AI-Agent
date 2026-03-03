# ==============================================================================
# Internal Knowledge AI Agent — Makefile
# ==============================================================================

.DEFAULT_GOAL := help
.PHONY: help dev dev-d down down-v build test test-cov test-e2e test-e2e-headed test-e2e-report lint format \
        migrate migrate-gen migrate-down migrate-history shell-backend logs

# Colours
GREEN  := \033[0;32m
YELLOW := \033[1;33m
RESET  := \033[0m

# Service name used in docker compose exec
BACKEND_SVC := backend

##@ Help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\n$(YELLOW)Usage:$(RESET)\n  make $(GREEN)<target>$(RESET)\n"} \
	     /^[a-zA-Z_0-9-]+:.*?##/ { printf "  $(GREEN)%-22s$(RESET) %s\n", $$1, $$2 } \
	     /^##@/ { printf "\n$(YELLOW)%s$(RESET)\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Development

dev: ## Start all 9 services and follow logs
	docker compose up --build

dev-d: ## Start all 9 services in detached mode
	docker compose up --build -d

down: ## Stop and remove containers (keeps volumes)
	docker compose down

down-v: ## Stop and remove containers AND named volumes
	docker compose down -v

build: ## Rebuild all images (no cache)
	docker compose build --no-cache

shell-backend: ## Open a bash shell inside the running backend container
	docker compose exec $(BACKEND_SVC) bash

logs: ## Tail logs (use SERVICE=<name> for a specific service)
	docker compose logs -f $(SERVICE)

##@ Testing

test: ## Run backend pytest + frontend tsc check
	@echo "$(YELLOW)--- Backend: pytest ---$(RESET)"
	docker compose exec $(BACKEND_SVC) \
	    python -m pytest tests/ -x -q
	@echo "$(YELLOW)--- Frontend: tsc --noEmit ---$(RESET)"
	cd frontend && npx tsc --noEmit
	@echo "$(GREEN)All tests passed$(RESET)"

test-cov: ## Run pytest with coverage gate ≥ 80 %
	docker compose exec $(BACKEND_SVC) \
	    python -m pytest tests/ \
	        --cov=src \
	        --cov-report=term-missing \
	        --cov-fail-under=80

test-e2e: ## Run Playwright end-to-end tests (headless)
	cd frontend && pnpm test:e2e

test-e2e-headed: ## Run Playwright E2E tests in headed mode (visible browser)
	cd frontend && pnpm test:e2e:headed

test-e2e-report: ## Open the last Playwright HTML report
	cd frontend && pnpm test:e2e:report

##@ Linting & Formatting

lint: ## Run ruff + mypy (backend) and biome check (frontend)
	@echo "$(YELLOW)--- ruff check ---$(RESET)"
	docker compose exec $(BACKEND_SVC) ruff check src/ tests/
	@echo "$(YELLOW)--- mypy ---$(RESET)"
	docker compose exec $(BACKEND_SVC) mypy src/
	@echo "$(YELLOW)--- biome check ---$(RESET)"
	cd frontend && npx biome check .
	@echo "$(GREEN)Lint passed$(RESET)"

format: ## Auto-format backend (ruff) and frontend (biome)
	docker compose exec $(BACKEND_SVC) ruff format src/ tests/
	cd frontend && npx biome format --write .

##@ Database / Migrations

migrate: ## Apply all pending Alembic migrations (upgrade head)
	docker compose exec $(BACKEND_SVC) alembic upgrade head

migrate-gen: ## Generate a new migration: make migrate-gen name=my_migration
	docker compose exec $(BACKEND_SVC) \
	    alembic revision --autogenerate -m "$(name)"

migrate-down: ## Roll back one migration (downgrade -1)
	docker compose exec $(BACKEND_SVC) alembic downgrade -1

migrate-history: ## Show Alembic migration history
	docker compose exec $(BACKEND_SVC) alembic history --verbose
