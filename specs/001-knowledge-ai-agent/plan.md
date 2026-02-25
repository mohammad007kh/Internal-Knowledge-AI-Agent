# Implementation Plan: Internal Knowledge AI Agent

**Branch**: `001-knowledge-ai-agent` | **Date**: 2026-02-25 | **Spec**: [specs/001-knowledge-ai-agent/spec.md](spec.md)
**Input**: Feature specification from `specs/001-knowledge-ai-agent/spec.md`

---

## Planning Configuration

**Configured At**: 2026-02-25

| Setting | Value |
|---------|-------|
| Subagents | Disabled — no `.specify/subagents/` folder found; general knowledge used |
| Available Subagents | None |
| Competitive Analysis | No |
| Review Depth | Full review |

---

## Summary

An internal, invite-only multi-source Agentic RAG platform that allows employees to ask natural language questions against registered internal data sources (PostgreSQL, MS SQL, MySQL, MongoDB, PDFs, Word, Excel, Markdown, CSV). Queries are routed through an 8-node LangGraph pipeline that retrieves relevant context, generates grounded responses, enforces company guardrail policies, and streams answers token-by-token with inline citations. Admins manage sources, users, access control, sync schedules, AI model configurations, and guardrail rules via a dedicated admin panel. The system bootstraps from environment configuration, deploys as 9 Docker Compose services, and uses pgvector (HNSW) for semantic search, MinIO for file storage, Celery + Redis for background ingestion/sync jobs, and Langfuse for LLM observability.

**Scope**: Full MVP — all 35 FRs across 9 user stories (3 P1, 4 P2, 2 P3).

---

## Technical Context

**Language / Runtime**: Python 3.12 (backend) + Node.js LTS (frontend via Next.js 15)

**Primary Dependencies**:
- Backend: FastAPI, LangChain, LangGraph, SQLAlchemy, Alembic, Celery, dependency-injector, Pydantic v2, bcrypt, python-jose, langfuse
- Frontend: Next.js 15 (App Router), React, shadcn/ui, Tailwind CSS, TanStack Query, React Hook Form, Zod
- Infrastructure: PostgreSQL 16 + pgvector, Redis, MinIO, Docker Compose

**Storage**: PostgreSQL 16 (app data + vectors via pgvector extension), MinIO (raw uploaded files), Redis (Celery broker + result backend)

**Testing**: pytest + httpx (backend unit + integration), Playwright (e2e)

**Target Platform**: Self-hosted Linux server via Docker Compose

**Performance Goals**: Typical query answered in < 30 s end-to-end (SC-001); 20 concurrent users with ≤ 100k indexed documents/rows (SC-009)

**Constraints**:
- Single-tenant deployment; invite-only auth (no self-registration)
- Celery Beat: `replicas: 1` strict (duplicate scheduler hazard)
- FR-033: auto-restart capped at 3 attempts; stop-and-alert on failure
- FR-035: upload hard-reject above configurable limit; default 50 MB defined in `app_config.yaml` (not `.env`, not hardcoded)

**Scale / Scope**: Medium — tens to hundreds of sources, ≤ 100k total documents / DB rows across the full deployment

---

## Tech Stack Approval

| Decision | Value | Source | Approved |
|---|---|---|---|
| Backend Language / Runtime | Python 3.12 | Registry | ✅ |
| Web Framework | FastAPI | Registry | ✅ |
| Agent Orchestration | LangChain + LangGraph | Spec | ✅ |
| ORM / Migrations | SQLAlchemy + Alembic | Registry | ✅ |
| Auth Method | JWT (15 min access token) + httpOnly refresh cookie (7 d) | Registry | ✅ |
| Authorization | RBAC — `admin` \| `user` | Registry | ✅ |
| Background Jobs | Celery + Redis (Beat: separate service, replicas: 1) | Registry | ✅ |
| Caching | Redis | Registry | ✅ |
| Vector Database | PostgreSQL 16 + pgvector (HNSW m=16, ef_construction=64) | Spec | ✅ |
| File Storage | MinIO — presigned PUT URL pattern | Spec | ✅ |
| IoC Container | dependency-injector (Protocol ABCs) | Spec | ✅ |
| LLM Observability | Langfuse (self-hosted) | Spec | ✅ |
| Frontend Framework | Next.js 15 (App Router) | Registry | ✅ |
| UI Library | shadcn/ui + Tailwind CSS | Registry | ✅ |
| State / Server State | React Context + TanStack Query | Registry | ✅ |
| Forms / Validation | React Hook Form + Zod | Registry | ✅ |
| Container Orchestration | Docker Compose (9 services) | Registry | ✅ |
| Testing (unit) | pytest | Registry | ✅ |
| Testing (integration) | httpx (HTTPX AsyncClient) | Registry | ✅ |
| Testing (e2e) | Playwright | Registry | ✅ |

**Assumptions Made**: None — all decisions trace directly to PRD v0.6 or spec.

**Approval Status**: ✅ Approved
**Approved By**: Human
**Approved At**: 2026-02-25
**Revisions**: None

---

## Coding Standards

### Naming Conventions

| Context | Convention | Example |
|---|---|---|
| Variables / Functions (Python) | snake_case | `get_user_by_id`, `source_id` |
| Classes (Python) | PascalCase | `VectorRepository`, `BaseConnector` |
| Constants (Python) | SCREAMING_SNAKE_CASE | `MAX_RETRY_ATTEMPTS = 3` |
| Files (Python modules) | snake_case | `vector_repository.py` |
| React components | PascalCase | `SourceCard`, `ChatMessage` |
| Component files (Next.js) | kebab-case | `source-card.tsx`, `chat-message.tsx` |
| Utility files (Next.js) | kebab-case | `date-utils.ts`, `api-client.ts` |
| Database tables | snake_case | `chat_sessions`, `source_access` |
| Database columns | snake_case | `created_at`, `user_id` |
| API endpoints | kebab-case plural resources | `/api/v1/chat-sessions` |
| CSS / Tailwind | kebab-case | `chat-bubble`, `source-badge` |
| Environment variables | SCREAMING_SNAKE_CASE | `DATABASE_URL`, `MINIO_ENDPOINT` |

### Tooling

| Tool | Configuration | Command |
|---|---|---|
| Linter (Python) | `pyproject.toml` — ruff | `ruff check .` |
| Formatter (Python) | `pyproject.toml` — ruff format | `ruff format .` |
| Type checker (Python) | `pyproject.toml` — mypy | `mypy .` |
| Linter (JS/TS) | `.eslintrc.json` | `pnpm lint` |
| Formatter (JS/TS) | `.prettierrc` | `pnpm format` |
| AI Code Assistant | `.github/skills/` (61 files) + `.vscode/settings.json` | All 61 skill files are auto-injected into every Copilot Chat session — browse by category in `.github/copilot-instructions.md` |

### Agreed Standards

- **Python Style**: PEP 8 enforced by ruff; all public functions typed with mypy strict
- **Pre-commit Hooks**: Yes (ruff + mypy + prettier)
- **Enforced in CI**: Yes (GitHub Actions)
- **Commit format**: Conventional Commits — `feat|fix|chore|docs|test|refactor(scope): message`
- **Branch format**: `NNN-description` (e.g., `001-knowledge-ai-agent`)

**Standards Approved By**: Human
**Standards Approved At**: 2026-02-25

---

## Tech Stack Validation

**Validation Date**: 2026-02-25
**Validation Status**: PASS (FastAPI v0.133.1 confirmed live; remaining packages validated after `pyproject.toml` is created in Phase 0)

### Validation Results

| Package | Status | Notes |
|---|---|---|
| FastAPI | ✅ PASS | v0.133.1, published 2026-02-25 |
| All remaining packages | ⏳ PENDING | Re-run `validate-tech-stack.ps1` after Phase 0 `pyproject.toml` is created |

### User Overrides

None.

**Validation Approval**: ✅ Accepted
**Validated At**: 2026-02-25

---

## Frontend/UI Specifications

**UI Specifications Status**: ✅ Approved

### Core UI Stack

| Setting | Value | Notes |
|---|---|---|
| UI Library | shadcn/ui + Tailwind CSS | Use shadcn CLI for component installation |
| Design System | CSS variables (shadcn defaults) | Customise via `globals.css` `:root` tokens |
| State Management | React Context + TanStack Query | Context: auth/user state; TanStack Query: all server state |
| Form Handling | React Hook Form + Zod | Zod schemas aligned with backend Pydantic models |
| Data Fetching | TanStack Query (`useQuery` / `useMutation`) | SSE streaming via native `fetch` + `ReadableStream` |
| Routing | Next.js App Router | Route groups: `(auth)`, `chat`, `admin` |

### UI Features

| Feature | Enabled | Implementation Notes |
|---|---|---|
| Dark Mode | ✅ | `next-themes` provider; shadcn `dark:` CSS variable variants |
| Responsive / Mobile-first | ✅ | Tailwind breakpoints; mobile-first layout |
| Accessibility (WCAG 2.1 AA) | ✅ | Radix UI primitives (via shadcn); keyboard nav; aria labels |
| Animations | ❌ | Not required for MVP |

### Component Standards

| Standard | Rule |
|---|---|
| Component naming | PascalCase |
| File naming | kebab-case |
| Props interface | TypeScript `interface` with `Props` suffix |
| Default exports | Named exports preferred; only Next.js pages use default export |
| Styling | Tailwind utility classes + `cn()` helper from shadcn |
| Test location | `__tests__/` co-located with feature folder |

### Additional UI Requirements

- SSE streaming: use native `fetch` + `ReadableStream` for token-by-token display; event types: `token`, `citations`, `guardrail_blocked`, `clarification_needed`, `done`
- Chat input: `Enter` to send, `Shift+Enter` for newline
- Admin panel: persistent sidebar navigation (sources, users, guardrails, LLM config, health)
- Citation display: inline `[1]` footnote markers; collapsible `<details>` references block below answer
- Sync progress: real-time progress polling (500ms) in source detail view
- FR-032 sync-in-progress banner: modal dialog with 3-choice radio (use old data / wait + rerun / cancel)

**UI Approved By**: Human
**UI Approved At**: 2026-02-25

---

## Constitution Check

| Gate | Status | Notes |
|---|---|---|
| Article IX Dir. 6 — HITL Tech Stack checkpoint | ✅ PASS | Approved 2026-02-25 |
| Article IX Dir. 6 — HITL UI Specs checkpoint | ✅ PASS | Approved 2026-02-25 |
| Article IX Dir. 7 — Registry loaded before planning | ✅ PASS | Seeded from PRD v0.6 + spec; changelog updated |
| Article IX Dir. 7 — Registry synced after planning | ✅ PASS | All decisions added; no new decisions remain unsynced |
| Station 06 — API Contracts | ✅ PASS | Endpoint summary below; full OpenAPI YAML output in Phase 0 |
| Station 07 — Data Architecture | ✅ PASS | Single-tenant; 17 tables; user isolation via `user_id` + `source_access` joins |
| Station 08 — Auth & RBAC | ✅ PASS | JWT + bcrypt; RBAC `admin`\|`user`; invite-only; no self-registration |
| Station 12 — CI/CD & Release | ⏳ PENDING | GitHub Actions CI workflow created in Phase 0 |
| Station 13 — Security Baseline | ✅ PASS | Threat model in PRD §18; guardrails §19; input sanitization; strict CORS |

---

## Project Structure

### SpecKit Documentation (this feature)

```
specs/001-knowledge-ai-agent/
├── spec.md                   ✅ complete
├── plan.md                   ✅ this file
├── checklists/
│   └── requirements.md       ✅ complete
├── data-model.md             → generated Phase 0
├── contracts/                → generated Phase 0
│   ├── auth.yaml
│   ├── sources.yaml
│   ├── chat.yaml
│   ├── users.yaml
│   └── admin.yaml
│
│   (created by /speckit.tasks):
├── index.md
├── traceability.md
└── tasks/
    └── T-NNN-*.md
```

### Repository Root Structure

```
backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── auth.py          # login, refresh, logout, password-reset, setup
│   │       ├── chat.py          # sessions + SSE message stream
│   │       ├── sources.py       # source CRUD, inspect, sync, access
│   │       ├── users.py         # user list, invite, deactivate
│   │       └── admin.py         # guardrails, LLM config, health log
│   ├── core/
│   │   ├── config.py            # pydantic-settings; reads env + app_config.yaml
│   │   ├── container.py         # dependency-injector IoC container
│   │   ├── security.py          # JWT encode/decode, bcrypt, password policy (FR-034)
│   │   └── events.py            # startup: run migrations, bootstrap admin (FR-024)
│   ├── domain/
│   │   ├── entities/            # pure Python dataclasses (no ORM deps)
│   │   │   ├── user.py
│   │   │   ├── source.py
│   │   │   ├── chat.py
│   │   │   └── guardrail.py
│   │   ├── interfaces/          # Protocol ABCs
│   │   │   ├── i_vector_repository.py
│   │   │   ├── i_connector.py
│   │   │   ├── i_file_storage.py
│   │   │   └── i_llm_provider.py
│   │   └── exceptions.py
│   ├── infrastructure/
│   │   ├── db/
│   │   │   ├── base.py          # SQLAlchemy declarative base
│   │   │   ├── models.py        # all ORM models (17 tables)
│   │   │   └── repositories/
│   │   │       ├── user_repository.py
│   │   │       ├── source_repository.py
│   │   │       ├── chat_repository.py
│   │   │       └── vector_repository.py   # implements IVectorRepository
│   │   ├── connectors/
│   │   │   ├── base.py                    # BaseConnector ABC
│   │   │   ├── postgres_connector.py
│   │   │   ├── mssql_connector.py
│   │   │   ├── mysql_connector.py
│   │   │   ├── mongodb_connector.py       # MongoQueryTool wrapper
│   │   │   └── document_connector.py      # PDF, Word, Excel, CSV, Markdown, text
│   │   ├── storage/
│   │   │   └── minio_storage.py           # implements IFileStorage; presigned PUT
│   │   ├── llm/
│   │   │   └── langchain_provider.py      # implements ILLMProvider; 10 LLM slots
│   │   └── vector/
│   │       └── pgvector_repository.py
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── user_service.py
│   │   ├── source_service.py
│   │   ├── ingestion_service.py
│   │   ├── sync_service.py
│   │   └── guardrail_service.py
│   ├── agent/
│   │   ├── state.py             # LangGraph AgentState TypedDict
│   │   ├── pipeline.py          # compile_graph() → callable entrypoint
│   │   └── nodes/
│   │       ├── input_guardrail.py    # node 1
│   │       ├── query_router.py       # node 2
│   │       ├── clarifier.py          # node 3 — interrupt() + resume
│   │       ├── retriever.py          # node 4 — vector search
│   │       ├── text_to_query.py      # node 5 — live DB query
│   │       ├── synthesizer.py        # node 6 — compose + cite
│   │       ├── output_guardrail.py   # node 7
│   │       └── reflector.py          # node 8 — off by default
│   └── tasks/
│       ├── celery_app.py        # Celery init + Redis broker config
│       ├── ingestion.py         # ingest_source.delay()
│       └── sync.py              # sync_source.delay() + Beat schedule
├── alembic/
│   ├── env.py
│   └── versions/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── app_config.yaml              # upload_max_size_mb: 50 + other runtime config (FR-035)
├── pyproject.toml               # ruff, mypy, pytest, dependencies
└── Dockerfile

frontend/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   ├── setup/page.tsx           # invitation accept + forced password change
│   │   └── password-reset/page.tsx
│   ├── chat/
│   │   ├── page.tsx                 # session list + new chat button
│   │   └── [sessionId]/page.tsx     # chat thread + SSE stream
│   ├── admin/
│   │   ├── layout.tsx               # sidebar nav
│   │   ├── sources/
│   │   │   ├── page.tsx             # source list
│   │   │   ├── new/page.tsx         # register source wizard
│   │   │   └── [sourceId]/page.tsx  # detail + sync + access management
│   │   ├── users/page.tsx
│   │   ├── guardrails/page.tsx
│   │   ├── llm-config/page.tsx
│   │   └── health/page.tsx
│   ├── layout.tsx
│   └── globals.css
├── components/
│   ├── chat/
│   │   ├── chat-input.tsx           # Enter=send, Shift+Enter=newline
│   │   ├── chat-message.tsx         # markdown + citation markers
│   │   ├── citation-block.tsx       # collapsible <details> references
│   │   ├── sync-status-banner.tsx   # FR-032: 3-way choice modal
│   │   └── streaming-text.tsx       # token-by-token SSE render
│   ├── admin/
│   │   ├── source-card.tsx
│   │   ├── source-form.tsx          # wizard: connection/upload → inspect → approve
│   │   ├── sync-progress.tsx        # real-time progress indicator (polling)
│   │   ├── user-table.tsx
│   │   ├── invite-modal.tsx
│   │   ├── guardrail-editor.tsx
│   │   └── health-log.tsx           # FR-033: crash/restart event log
│   └── shared/
│       ├── password-input.tsx       # FR-034: inline policy validation feedback
│       └── file-upload.tsx          # FR-035: client-side size check + API hard-reject
├── lib/
│   ├── api-client.ts                # TanStack Query hooks for all endpoints
│   ├── auth.ts                      # token storage + refresh interceptor
│   └── sse.ts                       # ReadableStream SSE reader
├── package.json
└── Dockerfile

docker-compose.yml                   # 9 services: services below
docker-compose.override.yml          # dev: volume mounts, hot-reload, exposed ports
.env.example                         # all required env keys (no values)
app_config.yaml                      # deploy-time config (upload_max_size_mb, etc.)
.github/
├── workflows/
│   └── ci.yml                       # lint, type-check, test, validate
├── skills/                          # 61 Copilot skill files (auto-loaded via .vscode/settings.json)
└── copilot-instructions.md          # skill index — searchable by category

# Docker Compose services (9 total):
# 1. frontend    — Next.js 15 (port 3000)
# 2. backend     — FastAPI (port 8000)
# 3. worker      — Celery worker (concurrency via env)
# 4. beat        — Celery Beat (replicas: 1 STRICT — no exceptions)
# 5. db          — PostgreSQL 16 + pgvector
# 6. redis       — Redis (broker + cache)
# 7. minio       — MinIO (port 9000 + 9001 console)
# 8. langfuse    — Langfuse UI + API
# 9. langfuse-db — Langfuse's PostgreSQL instance
```

---

## Data Model

_Full DDL with indexes and constraints in [data-model.md](data-model.md) (generated Phase 0)._

### Key Tables

| Table | Purpose | Key Columns |
|---|---|---|
| `users` | All user accounts | `id UUID PK`, `email UNIQUE`, `password_hash`, `role` (admin\|user), `must_change_password BOOL`, `is_active`, `created_at`, `updated_at` |
| `invitations` | Pending account invitations | `id UUID PK`, `email`, `role`, `token_hash`, `expires_at`, `accepted_at` |
| `password_reset_tokens` | One-time password reset tokens | `id UUID PK`, `user_id FK→users`, `token_hash`, `expires_at`, `used_at` |
| `sources` | Registered internal data sources | `id UUID PK`, `name`, `type` (database\|document), `mode` (live\|snapshot), `description`, `is_approved BOOL`, `citations_enabled BOOL`, `deleted_at` |
| `source_connections` | Encrypted connection config | `id UUID PK`, `source_id FK`, `connector_type`, `config_encrypted BYTEA` |
| `source_access` | User→source access grants | `user_id FK`, `source_id FK` (composite PK), `granted_at`, `granted_by FK` |
| `source_llm_configs` | Per-source LLM slot overrides | `source_id FK`, `stage` (retrieval\|text_to_query), `llm_slot_id FK` — composite PK |
| `source_sync_configs` | Sync scheduling | `source_id FK PK`, `mode` (manual\|scheduled\|delta), `cron_expression`, `last_synced_at` |
| `sync_logs` | History of sync operations | `id UUID PK`, `source_id FK`, `started_at`, `completed_at`, `status`, `records_added INT`, `records_changed INT`, `error_detail TEXT` |
| `document_chunks` | Chunked + embedded content | `id UUID PK`, `source_id FK`, `chunk_text TEXT`, `embedding VECTOR(1536)`, `metadata JSONB`, `document_name`, `page_or_row INT` |
| `chat_sessions` | Per-user conversation threads | `id UUID PK`, `user_id FK`, `title`, `created_at` |
| `chat_messages` | Individual conversation turns | `id UUID PK`, `session_id FK`, `role` (user\|assistant\|clarification), `content TEXT`, `citations JSONB`, `guardrail_blocked BOOL`, `created_at` |
| `company_policies` | Plain-language guardrail rules | `id UUID PK`, `rule_text TEXT`, `is_active BOOL`, `created_by FK`, `created_at` |
| `guardrail_events` | Audit log of guardrail activations | `id UUID PK`, `message_id FK`, `policy_id FK` (nullable for baseline), `original_content TEXT`, `trigger_reason`, `action_taken`, `stage` (input\|output), `created_at` |
| `llm_configurations` | Named LLM slots (max 10) | `id UUID PK`, `slot_name`, `provider`, `model_name`, `temperature`, `max_tokens`, `api_key_encrypted BYTEA`, `is_default BOOL` |
| `embedding_model_configs` | Active embedding model | `id UUID PK`, `provider`, `model_name`, `dimensions INT`, `is_active BOOL` |
| `system_health_events` | FR-033 crash/restart audit | `id UUID PK`, `component_name`, `event_type` (crash\|restart_attempt\|restart_ok\|restart_failed), `attempt_number INT`, `error_detail TEXT`, `timestamp` |

**pgvector HNSW index DDL**:
```sql
CREATE INDEX ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

---

## API Contracts

_Full OpenAPI YAML in [contracts/](contracts/) (generated Phase 0)._

### Endpoint Summary

#### Auth — `POST|GET /api/v1/auth`

| Method | Path | Auth Required | Description |
|---|---|---|---|
| POST | `/auth/login` | Public | Email + password → JWT access + set refresh cookie |
| POST | `/auth/refresh` | httpOnly cookie | Rotate refresh token → new access token |
| POST | `/auth/logout` | Bearer | Revoke current refresh token |
| POST | `/auth/password-reset` | Public | Request reset link by email |
| POST | `/auth/password-reset/confirm` | Public | Set new password with reset token |
| POST | `/auth/setup` | Public (invitation token) | Accept invitation + set password |
| POST | `/auth/change-password` | Bearer | Voluntary or forced password change |

#### Users — `/api/v1/users`

| Method | Path | Auth Required | Description |
|---|---|---|---|
| GET | `/users` | Admin | List all users (paginated, offset) |
| POST | `/users/invitations` | Admin | Create + send invitation by email |
| PATCH | `/users/{user_id}/role` | Admin | Change user role |
| DELETE | `/users/{user_id}` | Admin | Deactivate user account |

#### Sources — `/api/v1/sources`

| Method | Path | Auth Required | Description |
|---|---|---|---|
| GET | `/sources` | Bearer | List sources visible to the caller (all for admin; granted for user) |
| POST | `/sources` | Admin | Register new source (database or document) |
| GET | `/sources/{source_id}` | Bearer | Source detail + sync status |
| PATCH | `/sources/{source_id}` | Admin | Update metadata, approve description, toggle citations |
| DELETE | `/sources/{source_id}` | Admin | Soft-delete source + cascade deactivate chunks |
| POST | `/sources/{source_id}/inspect` | Admin | Re-trigger schema/content inspection |
| POST | `/sources/{source_id}/sync` | Admin | Manual sync trigger |
| GET | `/sources/{source_id}/sync/status` | Admin | Current sync progress (% complete, records, estimated time) |
| GET | `/sources/{source_id}/upload-url` | Admin | Get presigned MinIO PUT URL for file upload |
| GET | `/sources/{source_id}/access` | Admin | List users with access |
| PUT | `/sources/{source_id}/access/{user_id}` | Admin | Grant user access |
| DELETE | `/sources/{source_id}/access/{user_id}` | Admin | Revoke user access |

#### Chat — `/api/v1/chat`

| Method | Path | Auth Required | Description |
|---|---|---|---|
| GET | `/chat/sessions` | Bearer | List user's sessions (paginated) |
| POST | `/chat/sessions` | Bearer | Create new session |
| GET | `/chat/sessions/{session_id}` | Bearer | Full session history |
| DELETE | `/chat/sessions/{session_id}` | Bearer | Delete session + messages |
| POST | `/chat/sessions/{session_id}/messages` | Bearer | Submit message → SSE stream response |

**SSE stream events** (per message response):
```
event: token
data: {"content": "word "}

event: citations
data: {"citations": [{"index": 1, "source": "HR Policy", "document": "leave-policy.pdf", "excerpt": "Remote employees are entitled to..."}]}

event: guardrail_blocked
data: {"reason": "This response was blocked by company policy."}

event: clarification_needed
data: {"question": "Did you mean Q3 FY2025 EMEA revenue or Q3 FY2025 EMEA headcount?"}

event: done
data: {"message_id": "uuid", "usage": {"prompt_tokens": 312, "completion_tokens": 128}}
```

#### Admin — `/api/v1/admin`

| Method | Path | Auth Required | Description |
|---|---|---|---|
| GET | `/admin/guardrails` | Admin | List company policy rules |
| POST | `/admin/guardrails` | Admin | Create rule |
| PATCH | `/admin/guardrails/{rule_id}` | Admin | Update or toggle rule |
| DELETE | `/admin/guardrails/{rule_id}` | Admin | Delete rule |
| GET | `/admin/guardrails/events` | Admin | Paginated guardrail audit log |
| GET | `/admin/llm-config` | Admin | List 10 LLM slot configurations |
| PUT | `/admin/llm-config/{slot_id}` | Admin | Configure LLM slot |
| GET | `/admin/health` | Admin | System component health + status |
| GET | `/admin/health/events` | Admin | FR-033 crash/restart event log (paginated) |

#### Config — `/api/v1/config`

| Method | Path | Auth Required | Description |
|---|---|---|---|
| GET | `/config/limits` | Public | Returns `upload_max_size_mb` + `supported_file_types` (for frontend FR-035 validation) |

---

## Implementation Phases

### Phase 0 — Foundation & Infrastructure
_Prerequisite for all phases_

**Goal**: Running 9-service Docker Compose stack; database schema applied; IoC skeleton wired; CI green.

**Deliverables**:
- `docker-compose.yml` with all 9 services and healthchecks
- `docker-compose.override.yml` — dev volume mounts + hot-reload
- `alembic/` initialised; initial migration: pgvector extension, all 17 tables, HNSW index
- `app/core/config.py` — Pydantic Settings: env vars + `app_config.yaml` (FR-035: upload_max_size_mb)
- `app/core/container.py` — dependency-injector container with all Protocols registered (stub implementations)
- `app/core/events.py` — startup lifecycle: run pending migrations, bootstrap admin check (FR-024)
- `app_config.yaml` — `upload_max_size_mb: 50`, `supported_file_types: [pdf, docx, xlsx, csv, txt, md]`
- `.env.example` — all required env keys documented with descriptions
- `pyproject.toml` — Python deps, ruff, mypy, pytest configuration
- `frontend/package.json` + `next.config.ts` — Next.js 15 + shadcn initialised
- `.github/workflows/ci.yml` — lint (ruff + eslint), type-check (mypy + tsc), tests (pytest + playwright)
- `data-model.md` — full DDL with all table definitions, constraints, and indexes
- `contracts/*.yaml` — OpenAPI YAML for all 5 endpoint groups (auth, users, sources, chat, admin)

**Gate criteria**:
- [ ] `docker compose up` → all 9 services report healthy
- [ ] `alembic upgrade head` applies cleanly on empty database
- [ ] pgvector HNSW index confirmed: `\d document_chunks` shows index type `hnsw`
- [ ] `pytest --collect-only` finds test structure without import errors
- [ ] CI passes on first green commit

---

### Phase 1 — Authentication & User Management
_Prerequisite: Phase 0_

**Covers**: US3 (P1 — Bootstrap), US6 (P2 — Invite user) | **FRs**: FR-021–024, FR-034

**Deliverables**:
- `app/infrastructure/db/models.py` — `User`, `Invitation`, `PasswordResetToken` ORM models
- `app/domain/interfaces/` — all 4 Protocol ABCs defined (implementations can be stubs)
- `app/core/security.py` — JWT sign/verify (python-jose), bcrypt hash/verify, `validate_password_policy()` (FR-034)
- `app/core/events.py` — bootstrap admin: read env `BOOTSTRAP_ADMIN_EMAIL` + `BOOTSTRAP_ADMIN_PASSWORD`, create user if `users` table empty, set `must_change_password=True`
- `app/services/auth_service.py` — login, refresh rotation, logout, password reset request/confirm, forced change
- `app/services/user_service.py` — invite creation (token + expiry), accept invitation, role update, deactivate
- `app/api/v1/auth.py` — all 7 auth endpoints
- `app/api/v1/users.py` — 4 user/invitation endpoints
- Frontend: `(auth)/login/page.tsx`, `(auth)/setup/page.tsx`, `(auth)/password-reset/page.tsx`
- `components/shared/password-input.tsx` — show/hide toggle + inline policy rule messages (FR-034)
- TanStack Query auth hooks, Zod schemas, refresh interceptor in `lib/auth.ts`

**Gate criteria**:
- [ ] Fresh deploy → bootstrap admin created; `must_change_password=True`
- [ ] Bootstrap admin logs in → forced to change password; subsequent logins not forced
- [ ] Second deploy with existing users → no duplicate bootstrap admin (idempotent)
- [ ] Login → 200 with `access_token` + `Set-Cookie: refresh_token` (httpOnly, SameSite=Strict)
- [ ] Expired access token → 401; `/auth/refresh` with valid cookie → new access token
- [ ] Admin invites user → user accepts (within 48h) → logs in with assigned role
- [ ] Expired invitation link → 410 with clear expiry message
- [ ] Password `abc` rejected; `Abcde123` accepted; error message names which rule failed (FR-034)
- [ ] No `/auth/register` or `/signup` endpoint exists

---

### Phase 2 — Document Source Ingestion
_Prerequisite: Phase 1_

**Covers**: US2 (P1 — Register document source) | **FRs**: FR-012, FR-013, FR-015, FR-020, FR-035

**Deliverables**:
- `app/infrastructure/connectors/base.py` — `BaseConnector` ABC: `test_connection()`, `inspect() → description`, `ingest()`, `delta_ingest()`
- `app/infrastructure/connectors/document_connector.py` — parsers: PyMuPDF (PDF), python-docx (Word), openpyxl (Excel), csv stdlib, markdown, plain text; chunking strategy (512 tokens, 64 overlap)
- `app/infrastructure/storage/minio_storage.py` — `IFileStorage` implementation; `generate_presigned_put_url()`, `download()`, `delete()`
- `app/infrastructure/vector/pgvector_repository.py` — `IVectorRepository`: `upsert_chunks()`, `semantic_search(query_vector, source_ids, top_k)`, `delete_by_source()`
- `app/infrastructure/llm/langchain_provider.py` — `ILLMProvider`: wraps `BaseChatModel` for active LLM slot; `embed_texts()` via active embedding model
- `app/tasks/ingestion.py` — Celery task: `ingest_source(source_id)` → download from MinIO → parse → chunk → embed → upsert to pgvector → update `source_sync_configs.last_synced_at`
- `app/services/source_service.py` — CRUD, `generate_presigned_url()`, `approve_source()`, `get_description()`
- `app/api/v1/sources.py` — source endpoints + `GET /config/limits` (public, returns upload config)
- Frontend: `admin/sources/page.tsx`, `admin/sources/new/page.tsx` (wizard), `components/shared/file-upload.tsx`
- `file-upload.tsx`: check file size against `/api/v1/config/limits` before upload; reject with configured limit message (FR-035)

**Gate criteria**:
- [ ] Admin uploads valid PDF → presigned PUT URL returned → file in MinIO → ingestion task queued → chunks in `document_chunks`
- [ ] Source description generated by LLM and returned for admin review; admin can edit and approve
- [ ] File > 50MB rejected at client before upload AND at API if bypassed (FR-035 double enforcement)
- [ ] `.exe` file rejected: "Unsupported format. Supported: pdf, docx, xlsx, csv, txt, md"
- [ ] `config_encrypted` and MinIO internal URLs never appear in any API response (FR-020)
- [ ] Source `is_approved=False` → not queryable by users

---

### Phase 3 — Database Source Connectors
_Prerequisite: Phase 2_

**Covers**: US2 (P1 — Register database source) | **FRs**: FR-011, FR-013, FR-014, FR-015, FR-016

**Deliverables**:
- `app/infrastructure/connectors/postgres_connector.py` — SQLAlchemy Core; `test_connection()` + schema introspection + SQL query execution
- `app/infrastructure/connectors/mssql_connector.py` — pyodbc / SQLAlchemy MSSQL dialect
- `app/infrastructure/connectors/mysql_connector.py` — SQLAlchemy MySQL dialect
- `app/infrastructure/connectors/mongodb_connector.py` — Motor async client; MongoQueryTool for LangChain
- FR-014: re-inspection generates updated description; diff computed and shown to admin before approval
- Connection config encrypted at rest using Fernet symmetric key (key in env, never in `app_config.yaml`)
- Container wires correct connector implementation via `connector_type` field in `source_connections`

**Gate criteria**:
- [ ] Invalid Postgres connection string → clear error returned in < 10s
- [ ] Valid Postgres connection → schema introspected → LLM description generated → presented for approval
- [ ] Admin triggers re-inspection → before/after description diff surfaced (FR-014)
- [ ] `source_connections.config_encrypted` is a BYTEA blob; decryptable only via `IConnector.get_connection_config()`
- [ ] MongoDB connector executes aggregation pipeline and returns typed results

---

### Phase 4 — Sync Engine
_Prerequisite: Phase 3_

**Covers**: US8 (P3 — Sync management) | **FRs**: FR-016, FR-017, FR-032, FR-033

**Deliverables**:
- `app/tasks/sync.py` — Celery task: `sync_source(source_id, mode)` → full or delta re-ingest → publish progress to Redis pub/sub channel `sync:{source_id}`
- `app/tasks/celery_app.py` — Celery Beat: read `source_sync_configs` with `mode=scheduled` at startup; build beat schedule from cron expressions
- `app/api/v1/sources.py` — `POST /{source_id}/sync`, `GET /{source_id}/sync/status` (poll: reads Redis for progress)
- `app/core/health_monitor.py` — background task posting `system_health_events` rows; reads Docker restart count via socket or env-injected counter
- `docker-compose.yml` — `restart: on-failure` with Docker-level restart policy; internal counter tracked by `health_monitor.py` to enforce 3-attempt cap and fire `restart_failed` event
- `admin/health/page.tsx`, `components/admin/health-log.tsx`
- `admin/sources/[sourceId]/page.tsx` — sync progress polling at 500ms
- `components/chat/sync-status-banner.tsx` — FR-032: modal with 3-radio choice

**Gate criteria**:
- [ ] Manual sync trigger → `sync_logs` row created; progress visible via status endpoint as integer 0–100
- [ ] Scheduled source: Celery Beat triggers at correct cron time
- [ ] Delta sync (Postgres): only rows with `updated_at > last_synced_at` re-chunked and re-embedded
- [ ] Simulated worker crash → restarted automatically; on 4th failure → `system_health_events` row `event_type=restart_failed`; health panel shows alert ≤ 60s after event (SC-011)
- [ ] FR-033: system does NOT retry after 3rd failure — no infinite restart loop
- [ ] FR-032: querying a source with active sync → 3-way choice modal rendered; each choice behaves correctly

---

### Phase 5 — LangGraph Agent Pipeline & Chat
_Prerequisite: Phase 2 (vector store ready), Phase 3 (DB connectors ready)_

**Covers**: US1 (P1 — Q&A), US4 (P2 — Clarification), US7 (P2 — Citations) | **FRs**: FR-001–010, FR-019

**Deliverables**:
- `app/agent/state.py` — `AgentState`: `session_id`, `user_id`, `user_message`, `accessible_source_ids`, `route_decision`, `retrieved_chunks`, `db_query_results`, `clarification_question`, `answer`, `citations`, `guardrail_blocked`, `reflection_loop_count`
- `app/agent/nodes/input_guardrail.py` — evaluate message against active `company_policies` + baseline injection protection; produce `GuardrailEvent` if triggered
- `app/agent/nodes/query_router.py` — classify intent + select relevant `source_id`s within `accessible_source_ids`
- `app/agent/nodes/clarifier.py` — if router confidence below threshold: LangGraph `interrupt()` + set `clarification_question`; resume path handles user reply
- `app/agent/nodes/retriever.py` — `IVectorRepository.semantic_search()` using query embedding; top-k chunks
- `app/agent/nodes/text_to_query.py` — for live DB sources: generate SQL/MongoDB query via `ILLMProvider`; execute via `IConnector`; format result rows as context
- `app/agent/nodes/synthesizer.py` — compose answer with inline `[N]` markers; never fabricate (grounding prompt FR-007); attach citation objects
- `app/agent/nodes/output_guardrail.py` — evaluate answer against policies; block or sanitize
- `app/agent/nodes/reflector.py` — default disabled; when enabled, loops back to retriever if answer quality low (max 2 reflection loops)
- `app/agent/pipeline.py` — `compile_graph()`: StateGraph; Langfuse `CallbackHandler` attached
- `app/api/v1/chat.py` — `POST /sessions/{id}/messages`: run pipeline `.astream()` → map state events to SSE event types → async generator → `StreamingResponse`
- Frontend: `chat/[sessionId]/page.tsx`, `streaming-text.tsx`, `citation-block.tsx`, `chat-message.tsx`, `chat-input.tsx`

**Gate criteria**:
- [ ] User question → SSE stream opens → tokens arrive progressively → `done` event fires (SC-001: p95 ≤ 30s)
- [ ] Answer only references sources in `accessible_source_ids`; data from other sources never used (FR-019)
- [ ] Deliberate ambiguous question → `clarification_needed` event → user replies → agent resumes and answers (US4 SC-1, SC-2)
- [ ] Unambiguous question → no clarifying question (US4 SC-3)
- [ ] Inline `[1][2]` markers in answer; collapsible references block with source, document, excerpt (FR-008)
- [ ] User toggles citations off in UI → subsequent answers have no markers (FR-010)
- [ ] Source `citations_enabled=False` → no citations from that source regardless of user preference (FR-009)
- [ ] User with no accessible sources → "You have no accessible data sources" message (US1 SC-4)
- [ ] Langfuse: trace visible for every pipeline run with token counts, node latencies, model name (Constitution II)
- [ ] SC-002: cross-reference 10 random answers against cited sources — ≥ 9.5/10 grounded

---

### Phase 6 — Source Access Control
_Prerequisite: Phase 1 (users), Phase 2 (sources)_

**Covers**: US5 (P2 — Access control) | **FRs**: FR-018, FR-019

**Deliverables**:
- `app/infrastructure/db/repositories/source_repository.py` — `get_accessible_source_ids(user_id)`, `grant_access()`, `revoke_access()`
- `app/api/v1/sources.py` — access CRUD endpoints
- Agent `query_router` + `retriever` + `text_to_query` nodes receive `accessible_source_ids` from `AgentState`; populated at session start from DB
- Frontend: `admin/sources/[sourceId]/page.tsx` — access management table

**Gate criteria**:
- [ ] New source registered → `source_access` has 0 rows for it; no user can query it
- [ ] Admin grants user access → user's next query can use that source (SC-006: immediate effect)
- [ ] Admin revokes access → user's next query cannot use that source
- [ ] Admin view: source access table shows all granted users

---

### Phase 7 — Guardrails
_Prerequisite: Phase 5 (pipeline nodes already wired, stubs in place)_

**Covers**: US9 (P3 — Guardrail rules) | **FRs**: FR-025–029

**Deliverables**:
- `app/infrastructure/db/models.py` — `CompanyPolicy`, `GuardrailEvent` (data model already in Phase 0 migration)
- `app/services/guardrail_service.py` — `evaluate_input(message, policies) → GuardrailDecision`, `evaluate_output(answer, policies) → GuardrailDecision`, `log_event()`
- `app/agent/nodes/input_guardrail.py` — fully implemented (was stub in Phase 5): loads active policies, evaluates, logs
- `app/agent/nodes/output_guardrail.py` — fully implemented: evaluates answer, blocks or sanitizes
- Baseline protections: hardcoded prompt-injection + jailbreak detection prompts (FR-028) — active even with 0 company policies
- `app/api/v1/admin.py` — guardrail CRUD + events endpoints
- Frontend: `admin/guardrails/page.tsx` — rule editor + audit log table (paginated)

**Gate criteria**:
- [ ] 0 company policies configured → baseline jailbreak protection still blocks `"Ignore all previous instructions..."` attempts
- [ ] Rule "never reveal salary data" → message containing salary question → `guardrail_blocked` SSE event; message text replaced with policy explanation
- [ ] LLM generates answer containing salary data despite no explicit query → output guardrail blocks it before `done`
- [ ] Every activation logged to `guardrail_events` within 5s (SC-008); rows never deleted
- [ ] Admin audit log shows: original message, rule triggered, action taken (US9 SC-3)

---

### Phase 8 — LLM & Embedding Configuration
_Prerequisite: Phase 5_

**Covers**: Admin configuration | **FRs**: FR-030, FR-031

**Deliverables**:
- `app/infrastructure/db/models.py` — `LLMConfiguration` (10 slots), `EmbeddingModelConfig`, `SourceLLMConfig`
- `app/services/llm_config_service.py` — CRUD for LLM slots + per-source overrides; hot config reload
- `app/infrastructure/llm/langchain_provider.py` — resolves slot assignment at request time (no static binding); reads `SourceLLMConfig` for retrieval/text_to_query stages
- `app/api/v1/admin.py` — LLM config endpoints
- Frontend: `admin/llm-config/page.tsx` — 10 slot panels + source override table

**Gate criteria**:
- [ ] Admin changes default slot → next pipeline call uses new model (no restart required)
- [ ] Source override for `retrieval` stage → retriever node uses override model for that source only
- [ ] `api_key_encrypted` never returned in any API response (FR-020 equivalence)
- [ ] Slot with `is_default=True` used when no per-source override is configured

---

### Phase 9 — Testing, Polish & SC Verification
_Prerequisite: All phases complete_

**Goal**: Full test suite passing; all success criteria measured and passing; RFC 7807 error format on all endpoints.

**Deliverables**:
- `tests/unit/` — all services, connectors, node functions (target: ≥ 80% line coverage)
- `tests/integration/` — full auth flow, ingestion pipeline, chat session round-trip, access control enforcement, guardrail blocking
- `tests/e2e/` (Playwright) — login → ask question → verify answer + citations; admin: invite user, register source, configure guardrail
- FR-033 integration test: simulate worker crash 3× → verify `restart_failed` event logged; 4th crash → no retry
- FR-035 integration test: read `upload_max_size_mb` from `app_config.yaml`; change to 10 MB; verify new limit enforced without code deploy
- RFC 7807 error responses on all non-2xx paths (per `api.error_format: rfc7807` in registry)
- `GET /api/v1/config/limits` endpoint (public — used by frontend file-upload component)
- Load test (Locust): 20 concurrent users, 100k seeded chunks → SC-009 verification

**Gate criteria**:
- [ ] `pytest --cov` ≥ 80% line coverage (excluding `alembic/versions/`)
- [ ] All Playwright flows pass in CI
- [ ] SC-001: p95 end-to-end latency ≤ 30s under 20-user load test
- [ ] SC-009: 20 concurrent simulated users generate no 5xx errors or timeouts
- [ ] SC-006: access grant/revoke effect measurable within 1 request (no cache lag ≥ 1 query)
- [ ] SC-007: 100/100 guardrail-triggering messages blocked in automated test
- [ ] All error responses return `application/problem+json` with `type`, `title`, `status`, `detail` fields

---

## Milestone Summary

| # | Phase | User Stories | FRs | Priority Track |
|---|---|---|---|---|
| 0 | Foundation & Infrastructure | — | — | Critical Path |
| 1 | Authentication & User Management | US3, US6 | FR-021–024, FR-034 | Critical Path |
| 2 | Document Source Ingestion | US2 (docs) | FR-012, FR-013, FR-015, FR-020, FR-035 | Critical Path |
| 3 | Database Source Connectors | US2 (DBs) | FR-011, FR-013–016 | Parallel with Phase 2 after Phase 1 |
| 4 | Sync Engine | US8 | FR-016, FR-017, FR-032, FR-033 | Parallel with Phase 5 after Phase 3 |
| 5 | LangGraph Agent Pipeline | US1, US4, US7 | FR-001–010, FR-019 | Critical Path (needs Phase 2) |
| 6 | Source Access Control | US5 | FR-018, FR-019 | Parallel with Phase 5 |
| 7 | Guardrails | US9 | FR-025–029 | After Phase 5 |
| 8 | LLM & Embedding Configuration | — | FR-030, FR-031 | After Phase 5 |
| 9 | Testing, Polish & SC Verification | all | all | Final gate |

**Minimum Viable Q&A Loop (fastest path to a working demo)**:
```
Phase 0 → Phase 1 → Phase 2 → Phase 5
```
Users can log in, admins can register document sources, and the agent can answer questions with citations.

**Parallel tracks** (can develop simultaneously after Phase 0):
- Backend team A: Phase 1 → 2 → 5 (critical path)
- Backend team B: Phase 3 → 4 (DB connectors + sync)
- Frontend team: Phase 1 frontend while backend Phases 2–5 complete

---

## Complexity Tracking

| Item | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| LangGraph 8-node pipeline with `interrupt()` | Stateful multi-turn flow; conditional routing; clarification mid-conversation; guardrail nodes at both ends | A single LangChain chain cannot handle clarification interrupts or conditional node bypassing; chatbot-style prompt chaining loses structured state |
| IoC container (dependency-injector + Protocol ABCs) | Multiple connector implementations (4 DB types + document) and LLM providers must be swappable without changing business logic; testable with mocks | Manual factory functions do not enforce Protocol compliance; direct imports create coupling between business logic and infrastructure |
| Celery Beat as separate Docker Compose service (replicas: 1 STRICT) | Prevents duplicate scheduled sync jobs, which would cause data corruption (duplicate chunks re-ingested) if worker is scaled horizontally | Running Beat inside a `worker` container would require `--beat` flag; scaled workers would each run their own Beat scheduler → duplicate job firing |
| Presigned PUT URL (MinIO) | Files up to 50 MB go directly to MinIO without holding a FastAPI connection open; avoids OOM risk on concurrent uploads | Streaming file through FastAPI (`UploadFile`) holds the connection open for the full upload duration; 20 concurrent 50MB uploads = 1GB in-flight memory on backend |
| pgvector HNSW index in PostgreSQL | Approximate nearest-neighbor search over ≤ 100k vectors within existing PostgreSQL — no additional database service needed | Exact KNN scan (no index) is O(n) and too slow at 100k vectors; Qdrant/Weaviate/Chroma would add a 10th Docker Compose service with operational overhead and a new data store to back up |
