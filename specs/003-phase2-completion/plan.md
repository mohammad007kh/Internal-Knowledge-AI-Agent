# Implementation Plan: Phase 2 — Product Completion

**Branch**: `003-phase2-completion` | **Date**: 2026-04-21 | **Spec**: [spec.md](./spec.md)

---

## Planning Configuration

**Configured At**: 2026-04-21
**Detected Platform**: Web

| Setting              | Value                                                                 |
|----------------------|-----------------------------------------------------------------------|
| Platform             | Web (Next.js 15 + FastAPI)                                            |
| Subagents            | Enabled                                                               |
| Available Subagents  | ai-engineer, backend-architect, api-documenter, database-optimizer, frontend-developer, python-pro, typescript-pro, architect-reviewer |
| Competitive Analysis | None                                                                  |
| Review Depth         | Full                                                                  |

---

## Summary

Phase 2 closes the gap between the current working skeleton and the full product vision described in the original PRD. The application already has auth, user management, a LangGraph RAG pipeline, database models, and an admin analytics page. Phase 2 delivers: a guided source registration wizard (replacing the raw JSON form), real-time SSE chat streaming with citations and guardrails, admin pages for LLM configuration and company policy, completion of the users/sources/profile pages, navigation, and connector scheduling.

**Three hard constraints govern everything:**
1. File bytes must never pass through the FastAPI backend (MinIO presigned PUT).
2. Every LLM call must be Langfuse-traced (Constitution §II).
3. Celery Beat runs as a single replica — no duplicate scheduled jobs (Constitution §V).

---

## Technical Context

### Station Gate Verification

#### Station 06 — API Contracts ✓
- [x] OpenAPI covers all 20 new endpoints (see API Contracts section)
- [x] Error schema: RFC 7807 (`detail`, `type`, `title`, `status`) — registry standard
- [x] Auth scoping: `get_current_user` (any authenticated) or `require_admin` on every endpoint
- [x] Idempotency: Source creation is idempotent via `object_key`; chat messages are not retried
- [x] Pagination: offset-based (`limit`, `offset`, `total`) — registry standard

#### Station 07 — Data Architecture ✓
- [x] Tenancy: `single_tenant` — no `tenant_id` column needed; all users share one org
- [x] Enforcement: `get_current_user` + RBAC dependency on every route; repositories enforce ownership (user sees own sessions; admin sees all)
- [x] Baseline entities: User, Source, ChatSession, ChatMessage all exist; new columns via Alembic
- [x] Isolation: User can only read own chat sessions and messages; source access controlled via `source_permissions` table

#### Station 08 — Auth & RBAC ✓
- [x] Auth: JWT (15 min access + 7d rotating httpOnly refresh) — already implemented
- [x] RBAC: `admin` and `user` roles — already implemented
- [x] Permission matrix: see below
- [x] Audit: guardrail events already logged to `guardrail_events` table

**Permission Matrix (Phase 2 additions):**

| Action                        | Admin | User |
|-------------------------------|-------|------|
| POST /sources/inspect          | ✓     | ✗    |
| POST /sources/upload-url       | ✓     | ✗    |
| POST /sources/{id}/refresh-description | ✓ | ✗ |
| GET /sources/{id}/stats        | ✓     | ✗    |
| GET /admin/llm-settings        | ✓     | ✗    |
| PUT /admin/llm-settings/{stage}| ✓     | ✗    |
| POST /admin/llm-settings/{stage}/test | ✓ | ✗ |
| GET /admin/policy              | ✓     | ✗    |
| PUT /admin/policy              | ✓     | ✗    |
| GET /admin/guardrail-events    | ✓     | ✗    |
| GET /admin/guardrail-events/{id}| ✓    | ✗    |
| GET /users/invitations         | ✓     | ✗    |
| DELETE /users/invitations/{id} | ✓     | ✗    |
| PATCH /users/me                | ✓     | ✓    |
| GET /users/me                  | ✓     | ✓    |
| POST /chat/sessions            | ✓     | ✓    |
| PATCH /chat/sessions/{id}      | owner | owner|
| DELETE /chat/sessions/{id}     | owner | owner|
| GET /chat/sessions/{id}/messages| owner| owner|
| POST /chat/sessions/{id}/messages| owner| owner|

---

## Tech Stack Approval

**Approved**: 2026-04-21 by Human

| Decision             | Value                               | Source   |
|----------------------|-------------------------------------|----------|
| Backend Language     | Python 3.12                         | Registry |
| Web Framework        | FastAPI (latest stable)             | Registry |
| ORM                  | SQLAlchemy (async)                  | Registry |
| Database             | PostgreSQL 16 + pgvector            | Registry |
| Migrations           | Alembic (versioned)                 | Registry |
| Job Queue            | Celery + Redis                      | Registry |
| Auth                 | JWT — 15 min access / 7d refresh    | Registry |
| Auth Pattern         | RBAC (admin / user)                 | Registry |
| IoC Container        | dependency-injector                 | Registry |
| Frontend Framework   | Next.js 15 (App Router)             | Registry |
| UI Library           | shadcn/ui + Tailwind CSS v4         | Registry |
| State Management     | TanStack Query + React Context      | Registry |
| Form Handling        | React Hook Form + Zod               | Registry |
| API Versioning       | /api/v1/                            | Registry |
| Error Format         | RFC 7807 problem details            | Registry |
| Pagination           | Offset (limit / offset / total)     | Registry |
| File Storage         | MinIO presigned PUT (15 min TTL)    | Registry |
| LLM Observability    | Langfuse (self-hosted)              | Registry |
| SSE Streaming        | FastAPI StreamingResponse           | Registry (new) |
| Beat Scheduling      | Built-in polling task (60s, no pkg) | Registry (new) |

**No new packages required.**

---

## Tech Stack Validation

**Status**: PASS (2026-04-21)
All packages already present in `backend/pyproject.toml` and `frontend/package.json`.
No new dependencies introduced.

---

## Frontend/UI Specifications

| Setting       | Value                       |
|---------------|-----------------------------|
| UI Library    | shadcn/ui                   |
| Styling       | Tailwind CSS v4             |
| State Mgmt    | TanStack Query + Context    |
| Form Handling | React Hook Form + Zod       |
| Icons         | lucide-react                |
| Toasts        | sonner                      |
| Dark Mode     | Supported                   |
| Responsive    | Yes                         |
| Accessibility | WCAG-AA                     |

**SSE frontend pattern**: `fetch()` with `ReadableStream` (not `EventSource`) — allows POST requests with body and custom Authorization header. The `EventSource` API is GET-only and cannot send the JWT.

---

## Data Model

### Alembic Migrations Required (4 migrations)

#### Migration 0017 — Source fields

```sql
ALTER TABLE sources ADD COLUMN source_mode       VARCHAR NOT NULL DEFAULT 'snapshot';
  -- Values: 'snapshot' | 'live'
ALTER TABLE sources ADD COLUMN retrieval_mode    VARCHAR NOT NULL DEFAULT 'vector_only';
  -- Values: 'vector_only' | 'text_to_query' | 'hybrid'
ALTER TABLE sources ADD COLUMN description       TEXT;
ALTER TABLE sources ADD COLUMN sync_mode         VARCHAR NOT NULL DEFAULT 'manual';
  -- Values: 'manual' | 'scheduled' | 'delta'
ALTER TABLE sources ADD COLUMN sync_schedule     VARCHAR;   -- cron expression
ALTER TABLE sources ADD COLUMN last_synced_at    TIMESTAMPTZ;
ALTER TABLE sources ADD COLUMN status            VARCHAR NOT NULL DEFAULT 'pending';
  -- Values: 'pending' | 'ingesting' | 'ready' | 'error' | 'stale' | 'paused'
ALTER TABLE sources ADD COLUMN citations_enabled BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE sources ADD COLUMN file_storage_path VARCHAR;   -- MinIO object key (internal only)
ALTER TABLE sources ADD COLUMN next_sync_due_at  TIMESTAMPTZ;
  -- Set by check_scheduled_syncs task; used for efficient polling query
```

#### Migration 0018 — User fields

```sql
ALTER TABLE users ADD COLUMN full_name                   VARCHAR;
ALTER TABLE users ADD COLUMN show_citations_preference   BOOLEAN NOT NULL DEFAULT TRUE;
```

#### Migration 0019 — Chat message fields

```sql
ALTER TABLE chat_messages ADD COLUMN sources_cited  JSONB;
  -- [{"ref": 1, "source_name": "HR DB", "excerpt": "...", "page": null}]
ALTER TABLE chat_messages ADD COLUMN message_type   VARCHAR NOT NULL DEFAULT 'normal';
  -- Values: 'normal' | 'clarification_request' | 'clarification_response' | 'guardrail_blocked'
ALTER TABLE chat_messages ADD COLUMN is_partial     BOOLEAN NOT NULL DEFAULT FALSE;
  -- True if SSE stream was aborted before done event
```

#### Migration 0020 — New table: source_description_history

```sql
CREATE TABLE source_description_history (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id    UUID        NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  description  TEXT        NOT NULL,
  replaced_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  replaced_by  UUID        REFERENCES users(id)
);
CREATE INDEX ix_source_description_history_source_id
  ON source_description_history(source_id);
```

### Indexes (new)

```sql
-- Efficient polling query for scheduled syncs
CREATE INDEX ix_sources_sync_poll
  ON sources(sync_mode, next_sync_due_at)
  WHERE sync_mode = 'scheduled' AND status NOT IN ('ingesting', 'paused');

-- Source list queries
CREATE INDEX ix_sources_status ON sources(status);
```

### Entity Relationship Summary

```
users ──< source_permissions >── sources
users ──< chat_sessions ──< chat_messages
sources ──< source_description_history
sources ──< sync_jobs (existing)
llm_configurations (standalone, keyed by stage name)
company_policies (standalone, versioned)
guardrail_events ──> users (actor)
invitations ──> users (invited_by)
```

---

## API Contracts

All endpoints follow:
- Base URL: `/api/v1/`
- Auth: `Authorization: Bearer <access_token>` on every request
- Errors: RFC 7807 `{ "detail": "...", "type": "...", "status": 400 }`
- Dates: ISO 8601

### Source Endpoints (new)

---

**`POST /api/v1/sources/inspect`** — Admin only

Inspects a source's schema/content and returns an AI-generated description. Does NOT persist.

Request:
```json
{
  "source_type": "postgresql",
  "connection": {
    "host": "db.internal",
    "port": 5432,
    "database": "hrdb",
    "username": "readonly",
    "password": "secret",
    "ssl_mode": "require"
  }
}
```

Response `200`:
```json
{
  "description": "This PostgreSQL database contains employee records...",
  "schema_summary": {
    "table_count": 12,
    "estimated_row_count": 84200
  }
}
```

Errors: `400` (invalid config), `422` (connection failed — returns reason), `500` (AI generation failed — returns empty description, not an error)

---

**`POST /api/v1/sources/upload-url`** — Admin only

Returns a presigned MinIO PUT URL for direct browser-to-storage upload.

Request:
```json
{ "filename": "hr_policy.pdf", "content_type": "application/pdf" }
```

Response `200`:
```json
{
  "upload_url": "https://minio.internal/uploads/uuid-hr_policy.pdf?X-Amz-...",
  "object_key": "uploads/2026/04/uuid-hr_policy.pdf"
}
```

Errors: `400` (unsupported content type), `500` (MinIO unreachable)

---

**`POST /api/v1/sources`** — Admin only (existing endpoint, modified request body)

Structured body replaces raw `connection_config` JSON.

Request:
```json
{
  "name": "HR Database",
  "source_type": "postgresql",
  "connection": { ... },
  "description": "Contains employee and payroll data...",
  "sync_mode": "scheduled",
  "sync_schedule": "0 2 * * *",
  "retrieval_mode": "hybrid",
  "citations_enabled": true
}
```
For file sources: `"object_key": "uploads/2026/04/uuid-hr_policy.pdf"` replaces `connection`.

Response `201`: full source object (see GET /sources/{id})

---

**`GET /api/v1/sources`** — Admin only (existing, enhanced response)

Response `200`:
```json
{
  "items": [
    {
      "id": "uuid",
      "name": "HR Database",
      "source_type": "postgresql",
      "source_mode": "live",
      "retrieval_mode": "hybrid",
      "status": "ready",
      "citations_enabled": true,
      "sync_mode": "scheduled",
      "sync_schedule": "0 2 * * *",
      "last_synced_at": "2026-04-20T02:00:00Z",
      "document_count": 1842,
      "chunk_count": 9431,
      "created_at": "2026-04-01T10:00:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

Note: `connection_config`, `file_storage_path` MUST NEVER appear in responses.

---

**`GET /api/v1/sources/{id}/stats`** — Admin only

Response `200`:
```json
{
  "document_count": 1842,
  "chunk_count": 9431,
  "last_synced_at": "2026-04-20T02:00:00Z",
  "sync_job_count": 14
}
```

---

**`POST /api/v1/sources/{id}/refresh-description`** — Admin only

Re-runs schema inspection + AI generation. Does NOT save — admin must approve via `PATCH`.

Response `200`:
```json
{ "proposed_description": "Updated: This PostgreSQL database now contains..." }
```

---

### Admin: LLM Settings

**`GET /api/v1/admin/llm-settings`** — Admin only

Response `200`:
```json
{
  "stages": [
    {
      "stage": "synthesizer",
      "label": "Answer Synthesizer",
      "description": "Writes the final answer shown to users.",
      "provider": "openai",
      "model": "gpt-4o",
      "api_key_hint": "sk-...ab12",
      "base_url": null,
      "temperature": 0.7,
      "max_tokens": 2048,
      "enabled": true
    }
  ]
}
```

`api_key_hint` is the last 4 characters of the stored key. Full key is never returned.

---

**`PUT /api/v1/admin/llm-settings/{stage}`** — Admin only

Request:
```json
{
  "provider": "anthropic",
  "model": "claude-opus-4-7",
  "api_key": "sk-ant-...",
  "base_url": null,
  "temperature": 0.5,
  "max_tokens": 4096,
  "enabled": true
}
```

Response `200`: updated stage config (with `api_key_hint`, no full key)

---

**`POST /api/v1/admin/llm-settings/{stage}/test`** — Admin only

Sends a minimal test completion to verify the config works.

Response `200`:
```json
{ "success": true, "latency_ms": 342, "message": "Connection verified." }
```

Response `422`:
```json
{ "success": false, "message": "Invalid API key." }
```

---

### Admin: Company Policy

**`GET /api/v1/admin/policy`** — Admin only

Response `200`:
```json
{
  "id": "uuid",
  "content": "- Never discuss competitor products.\n- Always respond formally.",
  "version": 3,
  "created_at": "2026-04-20T09:00:00Z"
}
```

---

**`PUT /api/v1/admin/policy`** — Admin only

Request:
```json
{ "content": "- Updated rules..." }
```

Response `200`: new policy version object (same shape as GET)

---

**`GET /api/v1/admin/guardrail-events`** — Admin only

Query params: `limit`, `offset`, `guard_type` (input|output), `action` (blocked|sanitized)

Response `200`:
```json
{
  "items": [
    {
      "id": "uuid",
      "guard_type": "input",
      "trigger_reason": "jailbreak",
      "action": "blocked",
      "user_id": "uuid",
      "user_email": "alice@company.com",
      "created_at": "2026-04-21T10:00:00Z"
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

---

**`GET /api/v1/admin/guardrail-events/{id}`** — Admin only

Response `200`: same as list item + `original_input: string`

---

### Users

**`GET /api/v1/users/me`** — Any authenticated (enhance existing)

Response `200`:
```json
{
  "id": "uuid",
  "email": "alice@company.com",
  "full_name": "Alice Smith",
  "role": "admin",
  "show_citations_preference": true,
  "created_at": "..."
}
```

---

**`PATCH /api/v1/users/me`** — Any authenticated

Request (all fields optional):
```json
{
  "full_name": "Alice Smith",
  "show_citations_preference": false,
  "current_password": "oldpass",
  "new_password": "newpass123"
}
```

Password change requires `current_password`. Name/preference update does not.

Response `200`: updated user object

---

**`GET /api/v1/users/invitations`** — Admin only

Response `200`:
```json
{
  "items": [
    {
      "id": "uuid",
      "email": "bob@company.com",
      "role": "user",
      "invited_by_email": "alice@company.com",
      "expires_at": "2026-04-28T10:00:00Z",
      "status": "pending"
    }
  ],
  "total": 3,
  "limit": 20,
  "offset": 0
}
```

---

**`DELETE /api/v1/users/invitations/{id}`** — Admin only

Response `204`: No content

Errors: `404` (not found), `409` (already accepted — cannot cancel)

---

### Chat Endpoints (complete)

**`POST /api/v1/chat/sessions`**

Request: `{ "title": "Q3 Budget Questions", "source_ids": ["uuid1", "uuid2"] }`
Response `201`: `{ "id": "uuid", "title": "...", "created_at": "..." }`

---

**`PATCH /api/v1/chat/sessions/{id}`** — Owner only

Request: `{ "title": "New title" }`
Response `200`: updated session object

---

**`DELETE /api/v1/chat/sessions/{id}`** — Owner only

Soft-delete (sets `deleted_at`). Response `204`.

---

**`GET /api/v1/chat/sessions/{id}/messages`** — Owner only

Response `200`:
```json
{
  "items": [
    {
      "id": "uuid",
      "role": "user",
      "content": "What is our parental leave policy?",
      "message_type": "normal",
      "sources_cited": null,
      "is_partial": false,
      "created_at": "..."
    },
    {
      "id": "uuid",
      "role": "assistant",
      "content": "Our parental leave policy provides...",
      "message_type": "normal",
      "sources_cited": [{"ref": 1, "source_name": "HR Handbook", "excerpt": "...", "page": 12}],
      "is_partial": false,
      "created_at": "..."
    }
  ],
  "total": 2
}
```

---

**`POST /api/v1/chat/sessions/{id}/messages`** — Owner only — **SSE Stream**

Request: `{ "content": "What is our leave policy?", "source_ids": [] }`

Response: `Content-Type: text/event-stream`

```
event: token
data: {"delta": "Our"}

event: token
data: {"delta": " parental"}

event: citations
data: {"citations": [{"ref": 1, "source_name": "HR Handbook", "excerpt": "...", "page": 12}]}

event: done
data: {"session_id": "uuid", "message_id": "uuid", "total_tokens": 312}
```

Possible events: `token` | `citations` | `clarification_needed` | `guardrail_blocked` | `done` | `error`

Backend sequence:
1. Verify session ownership
2. Intersect requested `source_ids` with user's permitted sources
3. Persist user message to `chat_messages`
4. Run LangGraph pipeline (async generator), stream tokens via SSE
5. On `done` event: persist assistant message with `sources_cited` and `message_type`
6. On client abort (`AbortController.abort()`): persist partial message with `is_partial = true`

---

## Background Task

**`check_scheduled_syncs`** — Celery periodic task, every 60 seconds

```python
# Fires once per minute via static beat_schedule (already in celery config)
# Query: sources where sync_mode='scheduled' AND next_sync_due_at <= NOW()
#        AND status NOT IN ('ingesting', 'paused')
# For each: dispatch sync_source.delay(source.id), update next_sync_due_at
```

`next_sync_due_at` is computed from `sync_schedule` (cron expression) when:
- Source is first saved with `sync_mode = 'scheduled'`
- Source sync completes (compute next fire time from cron)
- Admin updates the schedule

---

## Implementation Phases

### Phase 2A — Core Loop (P0) — Estimated: ~8 tasks

The absolute minimum for a working end-to-end experience.

| # | Task | FR | Subagent |
|---|------|----|----------|
| T-001 | Alembic migrations 0017–0020 (all new columns + table) | FR-001 | database-optimizer |
| T-002 | Backend: `POST /sources/inspect` + `SourceInspectionService` | FR-004 | ai-engineer, python-pro |
| T-003 | Backend: `POST /sources/upload-url` (MinIO presigned PUT) | FR-006 | python-pro |
| T-004 | Backend: Refactor `POST /sources` to accept structured body | FR-001,002,007 | backend-architect |
| T-005 | Backend: `POST /chat/sessions/{id}/messages` SSE stream | FR-014,015,016,017,018 | ai-engineer, python-pro |
| T-006 | Frontend: Source registration wizard (5 steps) | FR-001–008 | frontend-developer, typescript-pro |
| T-007 | Frontend: Chat SSE streaming + message thread completion | FR-014–020 | frontend-developer, typescript-pro |
| T-008 | Frontend: Citation panel + clarification card + guardrail card | FR-016,017,018 | frontend-developer |

### Phase 2B — Admin Experience (P1) — Estimated: ~12 tasks

| # | Task | FR | Subagent |
|---|------|----|----------|
| T-009 | Backend: LLM settings CRUD + test endpoints | FR-021–024 | python-pro, backend-architect |
| T-010 | Backend: Policy CRUD + versioning | FR-025,026 | python-pro |
| T-011 | Backend: Guardrail events list + detail endpoints | FR-027,028 | python-pro |
| T-012 | Backend: Invitation list + cancel endpoints | FR-031 | python-pro |
| T-013 | Backend: `GET/PATCH /users/me` enhancements | FR-032,033,034 | python-pro |
| T-014 | Backend: `GET /sources/{id}/stats` + `POST /sources/{id}/refresh-description` | FR-012,013 | python-pro |
| T-015 | Frontend: Sources list — status badges, document count, sync now | FR-009,010 | frontend-developer |
| T-016 | Frontend: Source detail page — 4 tabs (Overview/Sync/Access/Settings) | FR-011,012,013 | frontend-developer |
| T-017 | Frontend: LLM Settings admin page | FR-021–024 | frontend-developer, typescript-pro |
| T-018 | Frontend: Company Policy + guardrail events page | FR-025–028 | frontend-developer |
| T-019 | Frontend: Users page — last login, source access tab, invitations table | FR-029–031 | frontend-developer |
| T-020 | Frontend: Admin + chat sidebars, navigation completion | FR-035,036,037 | frontend-developer |

### Phase 2C — Polish (P2) — Estimated: ~5 tasks

| # | Task | FR | Subagent |
|---|------|----|----------|
| T-021 | Frontend: Profile page (name, password, citation preference) | FR-032,033,034 | frontend-developer |
| T-022 | Backend: `check_scheduled_syncs` Celery task + `next_sync_due_at` logic | FR-038,039,040 | python-pro |
| T-023 | Frontend: Empty states for all list views | FR-041 | frontend-developer |
| T-024 | Frontend: Error states + retry for all data-loading pages | FR-042 | frontend-developer |
| T-025 | Frontend: Network offline toast notification | FR-043 | frontend-developer |

---

## Gate Compliance Checklist (Spec → Plan → Tasks)

### Station 06 (API Contracts)
- [x] OpenAPI covers all 20 new endpoints
- [x] Error schema standardized (RFC 7807)
- [x] Auth scoping documented per endpoint
- [x] Pagination defined (offset)
- [x] Idempotency noted where relevant

### Station 07 (Data Architecture)
- [x] Tenancy model: single_tenant (documented)
- [x] 4 Alembic migrations specified with exact SQL
- [x] Indexes planned (sync polling, status filter)
- [x] `connection_config` and `file_storage_path` excluded from all API responses

### Station 08 (Auth & RBAC)
- [x] Permission matrix defined for all new endpoints
- [x] Owner-only enforcement for chat session endpoints
- [x] Admin-only enforcement for all admin endpoints
- [x] Invitation cancellation: 409 if already accepted

---

## Assumptions & Deviations

- **SSE via `fetch()`**: EventSource API is not used because it cannot send POST bodies or Authorization headers. Frontend uses `fetch()` with `ReadableStream` decoder for SSE parsing.
- **File upload size limit**: 50 MB enforced by presigned URL TTL + MinIO server config, not by FastAPI middleware (constitution §VI).
- **AI description failure**: Returns `200` with empty description (not an error) — wizard degrades gracefully.
- **Guardrail events**: Assume `guardrail_events` table exists and has `original_input` + `trigger_reason` columns; if not, add via migration 0020 patch.
- **`GET /users/me`**: Endpoint likely exists — enhance response to include `full_name` and `show_citations_preference`.
- **Password change**: Reuses existing `POST /auth/change-password` endpoint; `PATCH /users/me` handles name + preference only (no password field in PATCH body to avoid confusion).
