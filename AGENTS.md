# AGENTS.md — Internal Knowledge AI Agent

This file is read by Codex at session start. It governs all AI-assisted development in this project.

## What This Project Is

An AI-powered internal knowledge retrieval and Q&A system. It indexes internal documents and surfaces relevant answers through a conversational interface using a 10-node LangGraph pipeline.

**Tech Stack:**
- Backend: Python 3.12 + FastAPI (modular monolith, clean architecture)
- Agent Pipeline: LangChain + LangGraph (10-node, Langfuse-traced)
- Frontend: Next.js 15 (App Router) + shadcn/ui + Tailwind CSS v4
- Database: PostgreSQL 16 + pgvector
- Jobs: Celery + Redis (Celery Beat = 1 replica only)
- Observability: Langfuse (self-hosted)
- Object Storage: MinIO
- Deployment: Docker Compose (9 services)

## Atomic Traceability Framework

This project uses the **Atomic Spec** governance framework. All feature development follows the four-phase pipeline:

```
/atomicspec.specify → /atomicspec.plan → /atomicspec.tasks → /atomicspec.implement
```

### Available Commands

| Command | Purpose |
|---|---|
| `/atomicspec.specify` | Create feature spec (`spec.md`) with gate checks |
| `/atomicspec.plan` | Build phased implementation plan with 4 HITL checkpoints |
| `/atomicspec.tasks` | Generate atomic task files (`tasks/T-XXX-name.md`) |
| `/atomicspec.implement` | Execute tasks under Context Pinning |
| `/atomicspec.analyze` | Analyze existing codebase for a feature area |
| `/atomicspec.analyze-competitors` | Run competitor analysis (Station 03) |
| `/atomicspec.checklist` | Run gate compliance checklist |
| `/atomicspec.clarify` | Clarify ambiguous requirements |
| `/atomicspec.constitution` | Regenerate this project's constitution |
| `/atomicspec.cleanup` | Detect and remove orphaned code |
| `/atomicspec.taskstoissues` | Export tasks to GitHub Issues |

### Prime Directives (Non-Negotiable)

1. **Directory Supremacy** — every feature gets `index.md` + `traceability.md`
2. **Atomic Injunction** — `/atomicspec.tasks` creates `tasks/T-XXX-[name].md` files, NEVER a single `tasks.md`
3. **Context Pinning** — during `/atomicspec.implement`, read ONLY `index.md`, the current task file, and `traceability.md`
4. **Gate Compliance** — Knowledge Station gates must pass before phase transitions
5. **Knowledge Routing** — unknown decisions consult `.specify/knowledge/stations/00-station-map.md` first
6. **Human-In-The-Loop** — `/atomicspec.plan` pauses at 4 mandatory checkpoints
7. **Project Defaults Registry** — all commands read `specs/_defaults/registry.yaml`
8. **Self-Contained Tasks** — task files embed all context needed for execution

### Project Defaults Registry

Canonical path: `specs/_defaults/registry.yaml`

Key decisions already locked:
- Architecture: `modular_monolith` / `clean` layers / `rest` API / `hybrid` communication
- Celery Beat: single replica (`replicas: 1`) — duplicate jobs = data corruption

### Project Constitution

See `memory/constitution.md` for the full set of non-negotiable architectural principles (Interface-First, LLM Observability, Connector Isolation, Agent Pipeline Safety, Security by Default, etc.).

## Knowledge Stations

Located in `.specify/knowledge/stations/`. Consult before phase transitions:

- `00-station-map.md` — routing guide
- `01-introduction.md` through `18-documentation.md`

## Subagents

Located in `.specify/subagents/`. Matched dynamically by semantic similarity to feature keywords — never hard-coded.

## Specs Layout

```
specs/
├── _defaults/
│   ├── registry.yaml      ← Project Defaults Registry (do not overwrite)
│   └── changelog.md
├── 001-knowledge-ai-agent/
└── 002-bug-fixes/
```

## Testing & Verification (READ before claiming "tests pass")

Backend tests run **inside the `internalknowledgeaiagent-backend-1` container**, and the source is **NOT live-mounted**. Before running pytest you MUST sync the WHOLE directories — copying a single changed file leaves the rest of the container stale and silently runs a partial/old suite (a false "green" that has masked real failures in this repo):

```bash
docker cp backend/src/. internalknowledgeaiagent-backend-1:/app/src/
docker cp backend/tests/. internalknowledgeaiagent-backend-1:/app/tests/
docker exec internalknowledgeaiagent-backend-1 python -m pytest tests/unit/ --no-cov -p no:cacheprovider -q
```

- **Cross-check the collected count** — the full backend unit suite is ≈ 1,900 tests. A much lower number means the container is stale; re-sync the full dirs.
- Lint on the **host** (not the container): `cd backend && python -m ruff check <changed files>` (and `--fix` for import-sort).
- For a single module, sync the full dirs anyway, then target the file: `pytest tests/unit/<path> -q`.

**Frontend tests run on the HOST, not in a container.** The `internalknowledgeaiagent-frontend-1` container is a runtime image (no devDeps/test binaries, source not live-mounted). Run from `frontend/`: `pnpm exec vitest run <file>` (unit), `pnpm exec tsc --noEmit` (types), `pnpm lint` / `pnpm exec biome check <paths>` (Biome — NEVER eslint). If `node_modules/.bin` is empty, `pnpm install --frozen-lockfile` first.

## Active Technologies
- Python 3.12 (backend), TypeScript 5.6 (frontend) + FastAPI, LangChain+LangGraph (existing pins), SQLAlchemy 2 async, Next.js 15, shadcn/ui, TanStack Query v5 — NO new runtime dependencies (004-agentic-pipeline)
- PostgreSQL 16 + pgvector (2 expand-only migrations: source-intent columns, message activity_summary JSONB); Redis (unchanged); MinIO (unchanged) (004-agentic-pipeline)

## Recent Changes
- **DB connection-retry & honest failure**: classify → retry → officially-fail with a categorised, secret-safe admin message (no DSN / host / port / user / password in messages, logs, API responses, or Langfuse traces); wired into the DB connector, schema-study, chat text-to-query, and the sources API + admin UI. Two expand-only migrations.
- **Guardrail session-scoping**: `GuardrailService` owns a `session_factory` and opens a short-lived session per DB touch (closed before the LLM eval) — scoping lives in the DI graph, not the API edge. SSE pipeline session-leak fixed.
- **CPU-only backend image**: ships CPU-only torch (dropped the ~2 GB CUDA stack); the runtime needs no GPU.
- **Feedback endpoint contract fix**: `raise` (not `return`) `problem()` so bad-rating / forbidden / not-found return 422 / 403 / 404 instead of 500.
- **004-agentic-pipeline**: plan-and-execute agentic graph behind `PIPELINE_AGENTIC_ENABLED` (default-off; admin-sandbox only, v2 graph is the rollback), replan / budget-guard / honest-failure nodes — NO new runtime dependencies.
