# CLAUDE.md — Internal Knowledge AI Agent

This file is read by Claude Code at session start. It governs all AI-assisted development in this project.

## What This Project Is

An AI-powered internal knowledge retrieval and Q&A system. It indexes internal documents and surfaces relevant answers through a conversational interface using an 8-node LangGraph pipeline.

**Tech Stack:**
- Backend: Python 3.12 + FastAPI (modular monolith, clean architecture)
- Agent Pipeline: LangChain + LangGraph (8-node, Langfuse-traced)
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
