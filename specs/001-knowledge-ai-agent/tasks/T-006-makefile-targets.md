# T-006 â€” Makefile targets (dev, test, lint, build, migrate)

## Metadata
| Field | Value |
|---|---|
| **Status** | Done |
| **ID** | T-006 |
| **Phase** | 0 â€” Foundation |
| **Group** | Setup Completion |
| **Priority** | P1 |
| **Estimated effort** | 1 h |
| **Depends on** | T-001, T-002, T-003, T-004, T-005 |
| **Blocks** | All subsequent tasks (used to run everything) |
| **FRs** | â€” |

---

## Goal
Create a root-level `Makefile` with consistent, self-documenting targets that wrap Docker Compose, pytest, ruff, mypy, Biome, TypeScript, and Alembic so every developer can operate the project with a single entry point.

---

## Acceptance Criteria
- [ ] `make help` prints all targets with one-line descriptions
- [ ] `make dev` starts all 9 Docker Compose services and follows logs
- [ ] `make down` stops and removes containers (keeps volumes)
- [ ] `make down-v` stops, removes containers **and** named volumes
- [ ] `make test` runs `pytest` (backend) + `npx tsc --noEmit` (frontend); exits non-zero if either fails
- [ ] `make test-cov` runs pytest with `--cov=src --cov-report=term-missing --cov-fail-under=80`
- [ ] `make lint` runs `ruff check` + `mypy src/` (backend) AND `biome check` (frontend); fails if any tool reports errors
- [ ] `make format` runs `ruff format` + `biome format --write`
- [ ] `make build` runs `docker compose build --no-cache`
- [ ] `make migrate` runs `alembic upgrade head` inside the `backend` service container
- [ ] `make migrate-gen name=<n>` runs `alembic revision --autogenerate -m <n>` inside `backend`
- [ ] `make migrate-down` runs `alembic downgrade -1` inside `backend`
- [ ] `make shell-backend` opens an interactive bash session in the running `backend` container
- [ ] `make logs SERVICE=<name>` tails logs for a specific service (defaults to all)
- [ ] `.PHONY` declared for every target

---

## Files to Create / Modify

### `Makefile` (project root)

```makefile
# ==============================================================================
# Internal Knowledge AI Agent â€” Makefile
# ==============================================================================

.DEFAULT_GOAL := help
.PHONY: help dev down down-v build test test-cov lint format migrate \
        migrate-gen migrate-down shell-backend logs

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

test-cov: ## Run pytest with coverage gate â‰¥ 80 %
	docker compose exec $(BACKEND_SVC) \
	    python -m pytest tests/ \
	        --cov=src \
	        --cov-report=term-missing \
	        --cov-fail-under=80

test-e2e: ## Run Playwright end-to-end tests
	cd frontend && npx playwright test

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
```

---

## Implementation Notes

1. **Docker Compose exec pattern** â€” all backend commands run inside the container so the host needs no Python environment.
2. **Frontend tsc** runs from the host (or a separate `node:18-alpine` service if CI runs inside Docker). For local dev, `cd frontend && npx tsc --noEmit` is sufficient.
3. **`SERVICE` variable** defaults to empty string so `docker compose logs -f` tails all services; if `SERVICE=backend` is passed it tails only the backend.
4. **`migrate-gen` pattern** â€” callers must pass `name=<slug>`; e.g. `make migrate-gen name=add_guardrail_events`.
5. **`make help` auto-discovery** â€” the `awk` pattern reads `##` doc comments from each target, so adding new targets requires only a `## Description` suffix.
6. **`make test`** uses `-x` (stop on first failure) and `-q` (quiet) for fast feedback loops; `test-cov` drops `-x` to report all coverage gaps.

---

## Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector |
| Frontend | Next.js 15 App Router Â· shadcn/ui Â· Tailwind CSS |
| State | React Context Â· TanStack Query Â· react-hook-form Â· Zod |
| Database | PostgreSQL 16 + pgvector Â· HNSW m=16 ef_construction=64 Â· UUID PKs Â· soft-delete + audit columns |
| Migrations | Alembic versioned |
| Background | Celery + Redis Â· Beat replicas=1 STRICT |
| File Storage | MinIO Â· presigned PUT pattern |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· bcrypt Â· RBAC (admin/user) |
| Encryption | Fernet (connection configs at rest) |
| AI Pipeline | LangGraph 8-node Â· interrupt() for clarification Â· SSE streaming |
| Tracing | Langfuse self-hosted Â· every pipeline run must emit a trace |
| Error Format | RFC 7807 Problem Details â€” all non-2xx API responses |
| Logging | Structured Â· INFO level Â· X-Request-ID correlation |
| Security | CORS strict Â· CSRF SameSite=Strict httpOnly Â· CSP moderate Â· rate-limit IP |
| UI | Dark mode Â· responsive Â· WCAG-AA Â· no animations Â· Lucide icons Â· Sonner toasts |
| Naming | snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants |
| Commits | Conventional commits Â· branch pattern: NNN-description |
| Testing | pytest + httpx + Playwright Â· â‰¥80% coverage |
| Infrastructure | Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db |

### Domain Rules
- Source access is per-user per-source; never expose unapproved source data (FR-019)
- Connection strings and file paths MUST NEVER appear in user-facing output, API responses, or AI content (FR-020)
- Celery Beat MUST run with exactly 1 replica â€” duplicate-schedule prevention is critical
- File size limit is defined in `app_config.yaml`; default 50 MB â€” NOT in .env, NOT hardcoded (FR-035)
- `bootstrap_admin` executes once on startup only if zero users exist (FR-024)
- Auto-restart is capped at 3 consecutive attempts with increasing wait; stop and alert admins on failure (FR-033)
- All passwords validated via `validate_password_policy()` â€” min 8 chars, â‰¥1 uppercase, â‰¥1 lowercase, â‰¥1 number (FR-034)
- Invitations are the only path to new accounts â€” no self-registration endpoint exists (FR-021)
- Every LangGraph pipeline run MUST emit a Langfuse trace with spans per node

---

## Gate Criteria
- `make help` prints without error
- `make lint` exits 0 on clean code
- `make test` exits 0 when all health checks pass
- `make migrate` runs successfully after `make dev-d`
