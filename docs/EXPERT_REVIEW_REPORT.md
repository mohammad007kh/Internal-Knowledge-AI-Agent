# Expert Review Report — Internal Knowledge AI Agent
**Date:** 2026-04-13  
**Branch:** develop  
**Reviewers:** Workflow & Routing, Security, Database, AI Pipeline, UI/UX, Architecture & Design Patterns

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Workflow & Routing Review](#1-workflow--routing-review)
3. [Security Review](#2-security-review)
4. [Database Review](#3-database-review)
5. [AI Pipeline Review](#4-ai-pipeline-review)
6. [UI/UX Review](#5-uiux-review)
7. [Architecture & Design Patterns Review](#6-architecture--design-patterns-review)
8. [Master Issue List](#7-master-issue-list)
9. [Remediation Roadmap](#8-remediation-roadmap)

---

## Executive Summary

Six expert teams reviewed the entire application — from first page to last, across all layers. The project has **strong architectural foundations** but contains **critical gaps in the admin panel** and several **security and database issues** that must be addressed before production.

### At a Glance

| Area | Verdict | Severity |
|---|---|---|
| Workflow & Routing | WARN | Admin panel 60% non-functional |
| Security | FAIL | 2 critical vulns (MinIO, SQL injection) |
| Database | FAIL | Broken migration chain, query bug, 9 missing tables |
| AI Pipeline | PASS (with gaps) | Citations not implemented, guardrails stubbed |
| UI/UX | PASS (with gaps) | Missing confirmations, UUID-based permissions |
| Architecture | PASS | Clean layering, DI complete, async correct |

### What Works
- Authentication flow (login, invite, password reset, change password)
- Regular user chat interface (SSE streaming, session management)
- Admin sources management (CRUD, permissions, sync history)
- LangGraph pipeline compilation and execution
- DI container, layering, async patterns
- Error handling (RFC 7807), CORS, rate limiting, JWT

### What Is Broken or Incomplete
- Admin connectors pages — no backend router (0% functional)
- Admin analytics dashboard — no backend endpoints
- Admin users management — endpoint path mismatches
- Vector search has a column name bug (`c.text` vs `c.chunk_text`)
- Migration chain 0002/0003 has reversed dependencies
- Citations not implemented (format_response is a no-op)
- Guardrails not active (policy evaluator is a stub)
- MinIO defaults to `minioadmin:minioadmin`
- SQL injection possible in database connector raw queries

---

## 1. Workflow & Routing Review

### Complete Page/Route Map

| Route | File | Access | Backend Endpoint(s) | Status |
|---|---|---|---|---|
| `/auth/login` | `(auth)/login/page.tsx` | Public | `POST /api/v1/auth/login` | ✅ |
| `/auth/setup` | `(auth)/setup/page.tsx` | Public (token) | `POST /api/v1/auth/setup` | ✅ |
| `/auth/password-reset` | `(auth)/password-reset/page.tsx` | Public | `POST /api/v1/auth/password-reset` | ✅ |
| `/auth/password-reset/confirm` | `(auth)/password-reset/confirm/page.tsx` | Public (token) | `POST /api/v1/auth/password-reset/confirm` | ✅ |
| `/auth/change-password` | `(auth)/change-password/page.tsx` | Protected (forced) | `POST /api/v1/auth/change-password` | ✅ |
| `/` | `(dashboard)/page.tsx` | Protected | Redirects → `/chat` | ✅ |
| `/chat` | `(dashboard)/chat/page.tsx` | Protected | `GET/POST /api/v1/chat/sessions`, SSE messages | ✅ |
| `/admin` | `(dashboard)/admin/page.tsx` | Admin only | `GET /admin/analytics/*`, `GET /health/detail` | ❌ No backend |
| `/admin/sources` | `(dashboard)/admin/sources/page.tsx` | Admin only | `GET/POST /api/v1/sources` | ✅ |
| `/admin/sources/new` | `(dashboard)/admin/sources/new/page.tsx` | Admin only | `POST /api/v1/sources`, `GET /api/v1/connectors` | ✅ |
| `/admin/sources/[id]` | `(dashboard)/admin/sources/[id]/page.tsx` | Admin only | `GET /api/v1/sources/{id}`, sync-jobs | ✅ |
| `/admin/sources/[id]/permissions` | `...permissions/page.tsx` | Admin only | `GET/POST/DELETE /api/v1/sources/{id}/permissions` | ✅ |
| `/admin/connectors` | `(dashboard)/admin/connectors/page.tsx` | Admin only | `GET /api/v1/connectors` | ❌ No backend |
| `/admin/connectors/new` | `(dashboard)/admin/connectors/new/page.tsx` | Admin only | `POST /api/v1/connectors` | ❌ No backend |
| `/admin/connectors/[id]` | `(dashboard)/admin/connectors/[id]/page.tsx` | Admin only | `GET/PUT/POST /api/v1/connectors/{id}` | ❌ No backend |
| `/admin/users` | `(dashboard)/admin/users/page.tsx` | Admin only | `GET /api/v1/admin/users` | ⚠️ Path mismatch |
| `/admin/users/new` | `(dashboard)/admin/users/new/page.tsx` | Admin only | `POST /api/v1/admin/users/invite` | ⚠️ Path mismatch |
| `/admin/users/[id]` | `(dashboard)/admin/users/[id]/page.tsx` | Admin only | `GET/PATCH /api/v1/admin/users/{id}` | ❌ Missing |

### User Journey

```
PUBLIC
  └─→ /auth/login (email + password)
        ├─→ [must_change_password=true] /auth/change-password
        └─→ /chat  (main interface)

INVITATION FLOW
  Admin: /admin/users/new → sends invite email
  User: /auth/setup?token=XXX → sets password → /auth/login → /chat

FORGOT PASSWORD
  /auth/login → /auth/password-reset → email sent
  /auth/password-reset/confirm?token=XXX → /auth/login
```

### Admin Journey

```
/admin (dashboard — metrics, health)
  ├─→ /admin/sources         (list/create)
  │     ├─→ /admin/sources/new
  │     └─→ /admin/sources/[id]
  │           └─→ /admin/sources/[id]/permissions
  ├─→ /admin/connectors      (list/create — NO BACKEND)
  ├─→ /admin/users           (list/invite — PARTIAL BACKEND)
  └─→ (analytics on /admin dashboard — NO BACKEND)
```

### Issues Found

#### CRITICAL — Missing Backend Routers

**Issue 1: Connectors router completely absent**
- Frontend pages: `/admin/connectors`, `/admin/connectors/new`, `/admin/connectors/[id]`
- Missing endpoints: `GET/POST/PUT/DELETE /api/v1/connectors`, `POST /api/v1/connectors/{id}/test`
- **Impact:** All connector management UI is non-functional

**Issue 2: Admin analytics endpoints absent**
- Dashboard calls: `GET /admin/analytics/activity`, `/admin/analytics/metrics`, `/admin/analytics/queries`, `/admin/analytics/top-sources`, `GET /health/detail`
- **Impact:** Admin dashboard is non-functional (empty metrics)

**Issue 3: Admin users endpoints path mismatch**

| Operation | Frontend Calls | Backend Has | Status |
|---|---|---|---|
| List users | `GET /admin/users?...` | `GET /users` | ⚠️ Path mismatch |
| Get user | `GET /admin/users/{id}` | MISSING | ❌ |
| Update user | `PATCH /admin/users/{id}` | MISSING | ❌ |
| Invite user | `POST /admin/users/invite` | `POST /users/invitations` | ⚠️ Path mismatch |
| Reset password | `POST /admin/users/{id}/reset-password` | MISSING | ❌ |

#### MEDIUM — Navigation & Error Pages

**Issue 4: No navigation links to admin pages**
- Sidebar only shows `/chat`; admins must manually type URLs
- Fix: Add conditional admin nav items based on `user.role === 'admin'`

**Issue 5: Missing 404/error pages**
- No `not-found.tsx` or `error.tsx` in Next.js app directory

### Verdicts

| Area | Status |
|---|---|
| Authentication flows | ✅ PASS |
| User chat flow | ✅ PASS |
| Admin — Sources | ✅ PASS |
| Admin — Connectors | ❌ FAIL |
| Admin — Users | ⚠️ WARN |
| Admin — Analytics Dashboard | ❌ FAIL |
| Routing & Navigation | ⚠️ WARN |

---

## 2. Security Review

### Findings

| Issue | Severity | Location | Recommendation |
|---|---|---|---|
| MinIO default credentials (`minioadmin:minioadmin`) | **CRITICAL** | `docker-compose.yml` | Remove fallback defaults entirely |
| `MINIO_SECURE=False` default | **CRITICAL** | `backend/src/core/config.py:22` | Default to `True`; reject `False` in production |
| SQL injection via f-string in database connector | **HIGH** | `backend/src/connectors/database_connector.py:116-119` | Validate query with SQL parser; whitelist SELECT only |
| X-Forwarded-For accepted from any IP (rate limit bypass) | **HIGH** | `backend/src/middleware/rate_limit.py:26-31` | Add trusted proxy configuration |
| HSTS set unconditionally (also sent over HTTP) | **HIGH** | `backend/src/middleware/security_headers.py:42` | Conditional on HTTPS/production environment |
| PostgreSQL connection errors may leak credentials | **MEDIUM** | `backend/src/connectors/postgres_connector.py:51-54` | Catch specific exceptions; return generic message |
| File upload validates extension only (no magic bytes) | **MEDIUM** | `backend/src/connectors/file_upload_connector.py:85-89` | Add `python-magic` MIME validation |
| Access token storage strategy unclear (httpOnly?) | **MEDIUM** | `frontend/src/lib/token-store.ts` | Confirm `__access` cookie is `httpOnly=True, Secure=True` |
| Encryption key stored as env var, no rotation | **MEDIUM** | `backend/src/core/config.py:32` | Migrate to secrets vault; implement key rotation |
| API docs (`/docs`, `/openapi.json`) exposed in all envs | **LOW** | `backend/src/main.py:37-38` | Disable in production (`ENVIRONMENT != "development"`) |
| SMTP credentials may appear in logs | **LOW** | `backend/src/core/config.py:37-41` | Explicit redaction |

### Detailed Notes

#### SQL Injection (HIGH)
File: `backend/src/connectors/database_connector.py:116-119`
```python
paged_sql = sa.text(
    f"SELECT * FROM ({self._query}) AS _q "  # noqa: S608
    f"LIMIT :limit OFFSET :offset"
)
```
`self._query` comes from admin-supplied source config. An admin user can inject arbitrary SQL. Fix: parse query with `sqlparse`, allow only basic SELECT statements.

#### MinIO (CRITICAL)
```yaml
MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:-minioadmin}
MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:-minioadmin}
```
Fallback defaults leave storage open if `.env` is missing or incomplete.

### Category Verdicts

| Category | Status | Key Issue |
|---|---|---|
| Authentication & Authorization | ⚠️ WARN | No account lockout, no MFA |
| Input Validation & Injection | ❌ FAIL | SQL injection in database connector |
| Secrets & Encryption | ⚠️ WARN | MinIO defaults, no key rotation |
| Network & API Security | ⚠️ WARN | X-Forwarded-For spoofing, MINIO_SECURE |
| Frontend Security | ✅ PASS | No dangerouslySetInnerHTML, httpOnly cookies |

---

## 3. Database Review

### Schema Completeness

| Table | ORM Model | Migration | Status |
|---|---|---|---|
| `users` | ✅ | 0003 | ✅ Implemented |
| `invitations` | ✅ | 0003 | ✅ Implemented |
| `password_reset_tokens` | ✅ | 0004 | ✅ Implemented |
| `user_refresh_tokens` | ✅ | 0002 | ✅ Implemented |
| `sources` | ✅ | 0006 | ✅ Implemented (missing columns vs spec) |
| `source_permissions` | ✅ | 0008 | ✅ Implemented (spec calls it `source_access`) |
| `documents` | ✅ | 0007 | ✅ Implemented |
| `chunks` | ✅ | 0007 | ✅ Implemented |
| `sync_jobs` | ✅ | 0009 | ✅ Implemented |
| `chat_sessions` | ✅ | 0010 | ✅ Implemented |
| `chat_messages` | ✅ | 0010 | ✅ Implemented |
| `system_health_events` | ✅ | 0012 | ✅ Implemented |
| `company_policies` | ✅ ORM | ❌ None | ❌ Missing migration |
| `llm_configurations` | ✅ ORM | ❌ None | ❌ Missing migration |
| `source_connections` | ❌ | ❌ | ❌ Missing entirely |
| `source_llm_configs` | ❌ | ❌ | ❌ Missing entirely |
| `source_sync_configs` | ❌ | ❌ | ❌ Missing entirely |
| `sync_logs` | ❌ | ❌ | ❌ Missing entirely |
| `guardrail_events` | ❌ | ❌ | ❌ Missing entirely |
| `embedding_model_configs` | ❌ | ❌ | ❌ Missing entirely |

### Critical Bugs

**Bug 1: Vector search references non-existent column**
- File: `backend/src/repositories/chunk_repository.py:84`
- Code: `SELECT c.id, c.source_id, c.text, ...` — column is `chunk_text` not `text`
- **Impact:** All vector similarity searches fail at runtime

**Bug 2: Broken migration dependency chain**
- Migration 0002 has `down_revision = "0003"` (points forward — impossible)
- Migration 0003 has `down_revision = "0001"` (skips 0002)
- **Impact:** `alembic upgrade head` may fail or apply in wrong order

**Bug 3: Invitation tokens stored unhashed**
- File: `backend/alembic/versions/0003_add_users_invitations.py`
- Raw UUID token stored directly; if DB is compromised, all invite links are exposed
- Fix: Store SHA-256 hash; look up by hash

### pgvector Configuration

| Parameter | Value | Status |
|---|---|---|
| Extension | `CREATE EXTENSION vector` | ✅ |
| Dimension | 1536 (text-embedding-3-small) | ✅ |
| Index type | HNSW with cosine ops | ✅ |
| m | 16 | ✅ |
| ef_construction | 64 | ✅ |
| ef_search | Not specified | ⚠️ Missing — add to index |

### Query Pattern Issues

| Issue | File | Impact |
|---|---|---|
| `c.text` instead of `c.chunk_text` | `chunk_repository.py:84` | Runtime crash |
| Double query in similarity_search (2 DB round-trips) | `chunk_repository.py:79-94` | Performance |
| RefreshTokenRepository uses explicit `.commit()` | `refresh_token_repository.py:60,71,83,108` | Breaks transaction atomicity |
| No connection pool size configured | `core/database.py` | Risk of pool exhaustion |

### Verdicts

| Area | Status |
|---|---|
| Schema & Models | ❌ FAIL — 9 missing tables, column bug |
| Migrations | ❌ FAIL — broken chain, 9 unmigrated tables |
| pgvector Configuration | ⚠️ WARN — missing ef_search |
| Query Patterns | ❌ FAIL — column name bug, broken atomicity |
| Data Integrity | ⚠️ WARN — chunks lack soft delete, tokens unhashed |
| Connection Pooling | ⚠️ WARN — not configured |

---

## 4. AI Pipeline Review

### Pipeline Architecture

```
START
  └─→ [1] load_history       — Fetch last 20 messages from DB
        └─→ [2] check_clarification  — Heuristic ambiguity detection
              ├─→ [True]  [3] handle_clarification → interrupt() → END
              └─→ [False] [4] retrieve_context     — Vector search (top-10)
                                └─→ [5] generate_response  — gpt-4o-mini (temp=0.2)
                                      └─→ [6] format_response  — (no-op in v1)
                                            └─→ [7] save_message — Persist to DB
                                                  └─→ END
```

### Strengths

- Pipeline correctly compiled; all edges defined
- State typed (`AgentState` TypedDict with `add_messages` reducer)
- Async-first — all nodes use `async def`
- Retry logic in `generate_response` (3 retries, exponential backoff 1s–8s)
- Langfuse traces on retrieve, clarify, generate nodes
- Proper SSE streaming with error events

### Issues Found

#### FAIL — Citations Not Implemented
- `format_response` node (node 6) is a literal no-op (`return {}`)
- `ChatResponse.sources` is always empty
- Users cannot verify where answers came from
- **Fix:** Inject `[1]`, `[2]` markers in `generate_response`; return chunk metadata in `done` SSE event

#### FAIL — Guardrails Not Enforced
- `guardrail_service.py` exists with `evaluate_input()` and `evaluate_output()` methods
- `_llm_evaluate()` always returns `False` (stub)
- Neither method is called from the pipeline
- **Fix:** Implement `_llm_evaluate()` with real LLM call or third-party (Llama Guard); call in pipeline

#### WARN — No Similarity Score Threshold
- All top-10 chunks returned regardless of relevance score
- If query has no semantic match, 10 irrelevant chunks are still used as context
- **Fix:** Add `WHERE score < 0.5` filter; return "no relevant context" message when all scores are poor

#### WARN — Prompt Not Hardened Against Injection
- User query directly interpolated into system prompt
- Retrieved context has no structural boundary markers
- **Fix:**
  ```
  <CONTEXT>
  {context}
  </CONTEXT>
  User question: "{query}"
  ```

#### WARN — No Token Budget Management
- No pre-calculation of context size before LLM call
- 10 chunks × ~100 tokens + system prompt + history could approach limits
- **Fix:** Calculate token count before sending; implement sliding window if needed

### RAG Quality

| Component | Status | Notes |
|---|---|---|
| Chunking | ✅ PASS | 512 tokens, 64 overlap, recursive splitter |
| Embedding | ✅ PASS | text-embedding-3-small, 100-batch async, 3-retry |
| Retrieval | ⚠️ WARN | Top-10 works; no threshold; no reranking |
| Generation | ✅ PASS | gpt-4o-mini, 0.2 temp, 1024 tokens max |
| Citations | ❌ FAIL | Not implemented |
| Guardrails | ❌ FAIL | Stubbed, not called |
| Streaming | ✅ PASS | Proper SSE, async generator, error handling |
| Observability | ✅ PASS | Langfuse traces on core nodes |

---

## 5. UI/UX Review

### Page-by-Page Summary

| Page | Status | Key Issues |
|---|---|---|
| `/auth/login` | ✅ PASS | Complete, accessible, proper validation |
| `/auth/setup` | ✅ PASS | Token validation, password rules enforced; no strength meter |
| `/auth/change-password` | ✅ PASS | Forced/voluntary flows both work |
| `/auth/password-reset` | ✅ PASS | Email enumeration safe |
| `/chat` | ✅ PASS | Streaming, sessions, citations, source selector |
| `/admin` (dashboard) | ⚠️ WARN | No backend for analytics; skeletal fallbacks only |
| `/admin/sources` | ⚠️ WARN | Missing delete confirmation dialog |
| `/admin/sources/[id]` | ✅ PASS | Tabs, sync history, documents |
| `/admin/sources/[id]/permissions` | ⚠️ WARN | UUID input (not email), no revoke confirmation |
| `/admin/connectors` | ❌ FAIL | No backend; UI renders but all calls fail |
| `/admin/users` | ⚠️ WARN | Partial backend; invite/edit broken |

### Forms Audit

| Form | Validation | Error Handling | Loading State | Issues |
|---|---|---|---|---|
| Login | ✅ | Toast + field errors | "Signing in…" | None |
| Setup Account | ✅ | Field errors, expired token | "Creating account…" | No strength meter |
| Change Password | ✅ | Field errors | "Saving…" | No strength meter |
| Password Reset | ✅ | Always succeeds (anti-enumeration) | "Sending…" | Correct by design |
| Create Source | ✅ | JSON parse errors | "Creating…" | Config JSON too technical |
| Invite User | ✅ | Field errors | "Sending…" | Good role description |
| Grant Permission | ❌ | Toast on error | Button disabled | UUID not email |
| Feedback | ✅ | Error toast only | None | Success toast missing |

### Critical UX Issues

**Issue 1: No delete confirmation on SourcesTable**
- Delete immediately removes source — no AlertDialog
- Fix: Copy UsersTable AlertDialog pattern

**Issue 2: Permission grants use UUID instead of email**
- Admins must know the user's UUID (not user-friendly)
- Fix: Email-based lookup with autocomplete

**Issue 3: No global error boundary**
- A single component crash can take down the whole dashboard
- Fix: Add `error.tsx` in `(dashboard)` and `(auth)` layouts

**Issue 4: Admin has no navigation links**
- Sidebar only shows Chat — admin must type URLs manually
- Fix: Conditional nav items per role

**Issue 5: Feedback cannot be changed after submission**
- Both thumbs-up/down buttons disabled once rating is set
- Fix: Allow re-rating

### Additional Issues by Severity

| Severity | Issue |
|---|---|
| High | Config JSON field is too technical for admins |
| High | No manual sync trigger button on source detail page |
| High | Permission revoke has no confirmation dialog |
| Medium | Chat input shows no character counter near limit |
| Medium | Dark mode badge colors may fail WCAG AA contrast |
| Medium | Admin mode not visually distinguished from user mode |
| Medium | Session delete dialog doesn't show session name |
| Medium | Invitation status (pending/accepted/expired) not visible |
| Low | No skip-to-content link |
| Low | Session rename/delete buttons not easily keyboard accessible |
| Low | No password strength meter on setup/change-password |

### Verdicts

| Area | Status |
|---|---|
| User flows & experience | ✅ PASS |
| Forms & validation | ✅ PASS (with caveats) |
| Loading & async states | ✅ PASS |
| Error handling | ✅ PASS (needs global boundary) |
| Accessibility | ⚠️ WARN |
| Component architecture | ✅ PASS |
| Admin-specific UX | ⚠️ WARN |
| Mobile & responsive | ✅ PASS |

---

## 6. Architecture & Design Patterns Review

### Architecture Diagram

```
┌────────────────────────────────────────────────┐
│           API LAYER  /api/v1/                  │
│  auth · sources · users · chat · sync_jobs     │
└──────────────────────┬─────────────────────────┘
                       │ Depends() injection
┌──────────────────────▼─────────────────────────┐
│           SERVICE LAYER  /services/             │
│  AuthService · SourceService · UserService      │
│  ChatSessionService · EmbeddingService          │
│  SyncJobService · EmailService · ...            │
└──────────────────────┬─────────────────────────┘
                       │ injected repos
┌──────────────────────▼─────────────────────────┐
│        REPOSITORY LAYER  /repositories/         │
│  BaseRepository[T] · UserRepo · SourceRepo      │
│  ChunkRepo · ChatRepo · SyncJobRepo · ...       │
└──────────────────────┬─────────────────────────┘
                       │
┌──────────────────────▼─────────────────────────┐
│            PERSISTENCE & INFRA                  │
│  PostgreSQL+pgvector · Redis · MinIO            │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│    AI AGENT PIPELINE  /agent/  (LangGraph)      │
│  8-node state graph · SSE streaming             │
│  Langfuse tracing · Fernet-encrypted configs    │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│       BACKGROUND WORKERS  (Celery)              │
│  sync_source · trigger_all_syncs                │
│  BaseTask (retries, Sentry, logging)            │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│       CONNECTOR PATTERN  /connectors/           │
│  BaseConnector (ABC) · Registry · Factory       │
│  confluence · sharepoint · google_drive · notion│
└────────────────────────────────────────────────┘
```

### DI Container Assessment

All services, repositories, connectors registered — **complete**.

| Component | Lifetime | Status |
|---|---|---|
| Repositories (10) | Factory (request-scoped) | ✅ |
| Services (10+) | Factory | ✅ |
| OpenAI client | Singleton | ✅ |
| Embedding service | Singleton | ✅ |
| Langfuse | Singleton | ✅ |
| Pipeline | Factory (with partial deps) | ✅ |

### Layering Violations — None Found

- ✅ Repositories: pure data access, no business logic
- ✅ Services: business rules + orchestration, no raw SQL
- ✅ API handlers: delegate to services; never access repos directly

### API Design

REST conventions properly followed throughout:
- 201 for creates, 204 for deletes, 202 for async jobs
- All responses use Pydantic models (no raw dicts)
- Versioned under `/api/v1/`
- RFC 7807 Problem Details for all errors

**Minor:** Some endpoints use `HTTPException` directly instead of `AppError` subclasses — inconsistent.

### Backend-Frontend Contract

| Entity | Match |
|---|---|
| Auth (TokenResponse) | ✅ Exact |
| SourceType enum | ✅ Exact |
| Source CRUD responses | ✅ Compatible |
| Chat session/message | ✅ Compatible |
| Field constraints | ✅ Aligned (maxLength, minLength) |

**Minor:** `latest_job` field in `SourceListItem` not documented in `specs/001/contracts/sources.yaml`.

### Async Patterns

- ✅ All I/O awaited; no blocking calls in async context
- ✅ `asyncio.gather()` for parallel embedding batches
- ✅ SSE streaming via `async def` generator
- ✅ Celery uses `asyncio.run()` bridge (acceptable pattern)
- ✅ Connection `pool_pre_ping=True`

**Minor:** No explicit `pool_size`, `max_overflow`, `pool_recycle` configured.

### Issues Found

| Issue | Severity | Location |
|---|---|---|
| Some endpoints use HTTPException instead of ForbiddenError | Minor | `sources.py`, `chat.py` |
| `COOKIE_SECURE=True` hardcoded (should be env-dependent) | Minor | `core/config.py` |
| `latest_job` undocumented in API contract | Minor | `specs/001/contracts/sources.yaml` |
| Connection pool not explicitly configured | Minor | `core/database.py` |

### Verdicts

| Area | Status |
|---|---|
| Dependency Injection | ✅ PASS |
| Layering | ✅ PASS |
| API Design | ✅ PASS |
| Backend-Frontend Contract | ✅ PASS |
| Error Handling (RFC 7807) | ✅ PASS |
| Async Patterns | ✅ PASS |
| Celery Task Architecture | ✅ PASS |
| Configuration Management | ✅ PASS |
| Connector Pattern | ✅ PASS |

---

## 7. Master Issue List

### CRITICAL (P0 — Must Fix Before Production)

| # | Issue | Location | Expert |
|---|---|---|---|
| C1 | MinIO default credentials (`minioadmin:minioadmin`) | `docker-compose.yml` | Security |
| C2 | `MINIO_SECURE=False` by default (plaintext object storage) | `core/config.py:22` | Security |
| C3 | SQL injection in database connector via f-string | `connectors/database_connector.py:116` | Security |
| C4 | Vector search crashes — `c.text` column does not exist (should be `c.chunk_text`) | `repositories/chunk_repository.py:84` | Database |
| C5 | Broken migration chain — 0002/0003 reversed dependencies | `alembic/versions/0002_*` and `0003_*` | Database |
| C6 | Admin connectors router missing — all 3 connectors pages non-functional | Backend has no `/api/v1/connectors` | Workflow |
| C7 | Admin analytics endpoints missing — dashboard non-functional | Backend has no `/admin/analytics/*` | Workflow |
| C8 | Citations not implemented — `format_response` is a no-op | `agent/nodes/format.py` | AI Pipeline |
| C9 | Guardrails not active — `_llm_evaluate()` always returns `False` | `services/guardrail_service.py` | AI Pipeline |

### HIGH (P1 — Before First Release)

| # | Issue | Location | Expert |
|---|---|---|---|
| H1 | X-Forwarded-For accepted without proxy validation (rate limit bypass) | `middleware/rate_limit.py:26` | Security |
| H2 | HSTS header set unconditionally (including HTTP) | `middleware/security_headers.py:42` | Security |
| H3 | Admin users endpoints have path mismatches — users management broken | `api/v1/users.py` vs frontend | Workflow |
| H4 | Invitation tokens stored unhashed | `alembic/versions/0003_*` | Database |
| H5 | 9 tables from spec missing migrations (`company_policies`, `llm_configurations`, etc.) | `alembic/versions/` | Database |
| H6 | `RefreshTokenRepository` explicit `.commit()` breaks transaction atomicity | `repositories/refresh_token_repository.py` | Database |
| H7 | No delete confirmation on SourcesTable | `admin/sources/_components/SourcesTable.tsx` | UI/UX |
| H8 | Permissions manager uses UUID instead of email | `admin/sources/[id]/permissions/` | UI/UX |
| H9 | No global error boundary | `app/(dashboard)/layout.tsx` | UI/UX |
| H10 | Admin has no navigation links to admin pages | Dashboard layout sidebar | Workflow / UI/UX |
| H11 | No similarity score threshold — irrelevant chunks used as context | `agent/nodes/retrieve.py` | AI Pipeline |
| H12 | Prompt not hardened against injection — no context boundary markers | `agent/prompts.py` | AI Pipeline |

### MEDIUM (P2 — Next Sprint)

| # | Issue | Location | Expert |
|---|---|---|---|
| M1 | PostgreSQL connection errors may leak credentials | `connectors/postgres_connector.py:51` | Security |
| M2 | File upload validates extension only, not magic bytes | `connectors/file_upload_connector.py:85` | Security |
| M3 | Encryption key stored as env var, no rotation mechanism | `core/config.py:32` | Security |
| M4 | API docs (`/docs`) exposed in all environments | `main.py:37` | Security |
| M5 | pgvector missing `ef_search` parameter | `alembic/versions/0007_*` | Database |
| M6 | Chunks have no soft delete mechanism | `models/chunk.py` | Database |
| M7 | Sources table missing columns from spec (`deleted_at`, `mode`, `is_approved`) | `models/source.py` | Database |
| M8 | Connection pool not configured (`pool_size`, `max_overflow`, `pool_recycle`) | `core/database.py` | Database / Architecture |
| M9 | No token budget management before LLM call | `agent/nodes/generate.py` | AI Pipeline |
| M10 | Config JSON field too technical for admin users | `admin/sources/_components/CreateSourceDialog.tsx` | UI/UX |
| M11 | No manual sync trigger button on source detail page | `admin/sources/[id]/page.tsx` | UI/UX |
| M12 | Invitation status (pending/accepted/expired) not visible on users list | `admin/users/page.tsx` | UI/UX |
| M13 | Permission revoke has no confirmation dialog | `admin/sources/[id]/permissions/` | UI/UX |
| M14 | `COOKIE_SECURE` hardcoded to `True` (breaks dev) | `core/config.py` | Architecture |
| M15 | HTTPException used instead of ForbiddenError in some endpoints | `api/v1/sources.py`, `api/v1/chat.py` | Architecture |
| M16 | Feedback buttons cannot be changed after submission | `components/feedback-buttons.tsx` | UI/UX |
| M17 | Dark mode badge colors may fail WCAG AA contrast | `components/SyncStatusBadge.tsx` | UI/UX |

### LOW (P3 — Backlog)

| # | Issue | Location | Expert |
|---|---|---|---|
| L1 | No account lockout after failed login attempts | `services/auth_service.py` | Security |
| L2 | No rate limiting on password-reset endpoint | `api/v1/auth.py` | Security |
| L3 | `similarity_search()` uses 2 queries instead of 1 | `repositories/chunk_repository.py` | Database |
| L4 | No reranking step after retrieval | `agent/nodes/retrieve.py` | AI Pipeline |
| L5 | Chunk deduplication happens at rendering, not retrieval | `agent/prompts.py` | AI Pipeline |
| L6 | Langfuse traces missing for `load_history`, `handle_clarification`, `save_message` | `agent/nodes/` | AI Pipeline |
| L7 | No skip-to-content link | Frontend layout | UI/UX |
| L8 | Session delete dialog does not show session title | `components/session-list.tsx` | UI/UX |
| L9 | No password strength meter on setup/change-password | `(auth)/setup/page.tsx` | UI/UX |
| L10 | `latest_job` not documented in API contract | `specs/001/contracts/sources.yaml` | Architecture |
| L11 | Missing 404/error pages | `app/` | Workflow |

---

## 8. Remediation Roadmap

### Phase 1 — P0: Production Blockers (Critical)

**Goal:** Make core functionality correct and secure.

| Task | Owner Domain | Effort |
|---|---|---|
| Fix `c.text` → `c.chunk_text` in chunk_repository.py | Backend | ~30 min |
| Fix migration 0002/0003 down_revision pointers | Backend | ~1 hr |
| Remove MinIO `minioadmin` fallback defaults | DevOps | ~30 min |
| Set `MINIO_SECURE: bool = True` as default | Backend | ~15 min |
| Add query validation/whitelisting in database_connector.py | Backend | ~4 hrs |
| Create `/api/v1/connectors` router with full CRUD | Backend | ~1 day |
| Create `/admin/analytics/*` router | Backend | ~1 day |
| Implement citations in `format_response` node | Backend | ~4 hrs |
| Implement guardrail `_llm_evaluate()` and wire into pipeline | Backend | ~1 day |

### Phase 2 — P1: Pre-Release Hardening

| Task | Owner Domain | Effort |
|---|---|---|
| Fix admin users endpoint paths and add missing endpoints | Backend | ~1 day |
| Add trusted proxy config to rate limiter | Backend | ~2 hrs |
| Conditionalise HSTS on HTTPS/production | Backend | ~1 hr |
| Hash invitation tokens (DB + service) | Backend | ~3 hrs |
| Create migrations for `company_policies`, `llm_configurations`, and remaining spec tables | Backend | ~2 days |
| Remove explicit `.commit()` from RefreshTokenRepository | Backend | ~1 hr |
| Add delete confirmation to SourcesTable | Frontend | ~1 hr |
| Switch permissions from UUID to email lookup | Full Stack | ~4 hrs |
| Add global error boundary (`error.tsx`) | Frontend | ~1 hr |
| Add admin navigation links to sidebar | Frontend | ~2 hrs |
| Add similarity score threshold to retrieval | Backend | ~1 hr |
| Harden system prompt with context boundary markers | Backend | ~1 hr |

### Phase 3 — P2: Quality & UX Polish

| Task | Owner Domain | Effort |
|---|---|---|
| Validate file magic bytes in upload connector | Backend | ~3 hrs |
| Configure database connection pool | Backend | ~1 hr |
| Add `ef_search` to HNSW index migration | Backend | ~30 min |
| Add soft delete to chunks table | Backend | ~2 hrs |
| Migrate encryption key to secrets vault | DevOps | ~1 day |
| Disable `/docs` in production | Backend | ~15 min |
| Add token budget calculation before LLM call | Backend | ~2 hrs |
| Replace Config JSON field with visual builder | Frontend | ~1 day |
| Add manual sync trigger to source detail page | Full Stack | ~3 hrs |
| Add invitation status column to users list | Full Stack | ~3 hrs |
| Add permission revoke confirmation dialog | Frontend | ~1 hr |
| Allow feedback rating changes | Frontend | ~1 hr |
| Fix dark mode badge contrast | Frontend | ~1 hr |
| Make COOKIE_SECURE env-dependent | Backend | ~30 min |
| Unify ForbiddenError usage (remove HTTPException) | Backend | ~1 hr |

### Phase 4 — P3: Backlog

- Account lockout after failed logins
- Rate limiting on password-reset endpoint
- Single-query refactor for similarity_search
- Reranking step in retrieval pipeline
- Chunk deduplication at retrieval time
- Add Langfuse traces to remaining pipeline nodes
- Frontend accessibility improvements (skip link, strength meter, etc.)
- Update API contract docs

---

## 9. Remediation Status Update

**Updated:** 2026-04-14 — Phases A–E completed on branch `develop`.

### Resolved Issues

| # | Issue | Status | Commit |
|---|---|---|---|
| C1 | MinIO default credentials removed | ✅ RESOLVED | 71e3c80 |
| C2 | `MINIO_SECURE=True` default set | ✅ RESOLVED | 71e3c80 |
| C4 | `c.text` → `c.chunk_text` in chunk_repository.py | ✅ RESOLVED | Phase A |
| C5 | Migration chain 0002/0003 validated (intentional order, docstrings updated) | ✅ RESOLVED | Phase A |
| C6 | Connectors router created — full CRUD + test endpoint | ✅ RESOLVED | a89d175 |
| C7 | Analytics router created — 5 endpoints | ✅ RESOLVED | a89d175 |
| C8 | Citations implemented — format_response extracts sources into SSE done event | ✅ RESOLVED | 4ccce99 |
| C9 | Guardrails activated — real LLM evaluation with policy injection hardening | ✅ RESOLVED | 4ccce99 / 366a0d3 |
| H1 | TRUSTED_PROXY_IPS added; X-Forwarded-For only trusted from known proxies | ✅ RESOLVED | 71e3c80 |
| H2 | HSTS conditional on HTTPS | ✅ RESOLVED | 71e3c80 |
| H3 | Admin users endpoint paths fixed (`/admin/users`), PATCH + lookup added | ✅ RESOLVED | a89d175 |
| H4 | Invitation tokens hashed with SHA-256 at service layer; double-hash bug fixed | ✅ RESOLVED | 71e3c80 / f3a95c6 |
| H5 | Migrations 0013 (company_policies), 0014 (llm_configurations), 0015 (last_login_at), 0016 (connectors) added | ✅ RESOLVED | Phase A / a89d175 |
| H6 | `RefreshTokenRepository` commit() → flush() throughout | ✅ RESOLVED | Phase A |
| H7 | AlertDialog confirmation added to SourcesTable delete | ✅ RESOLVED | 600c2b6 |
| H8 | Permissions manager updated to email lookup → UUID grant | ✅ RESOLVED | 600c2b6 |
| H9 | Error boundaries added (`(dashboard)/error.tsx`, `(auth)/error.tsx`) | ✅ RESOLVED | 600c2b6 |
| H10 | Admin nav links added to sidebar (role-conditional) | ✅ RESOLVED | 600c2b6 |
| H11 | Similarity threshold (0.4) added to retrieval node | ✅ RESOLVED | 4ccce99 |
| H12 | `<CONTEXT>` tags + injection-prevention instruction in system prompt | ✅ RESOLVED | 4ccce99 |
| M2 | python-magic MIME validation added to file upload connector | ✅ RESOLVED | 71e3c80 |
| M4 | `/docs` disabled when `ENVIRONMENT != "development"` | ✅ RESOLVED | 71e3c80 |
| M8 | Connection pool configured (`pool_size=10, max_overflow=20, pool_recycle=300`) | ✅ RESOLVED | Phase A |
| L11 | 404 page (`not-found.tsx`) and error boundaries added | ✅ RESOLVED | 600c2b6 |

### Additionally Fixed During Phase Reviews (Not in Original Report)

| Issue | Status | Commit |
|---|---|---|
| Double-hashing bug in invitation_repository (introduced during Phase B) | ✅ FIXED | f3a95c6 |
| `/health/detail` endpoint had no authentication | ✅ FIXED | 4ccce99 |
| `PUT /connectors/{id}` → `PATCH` (partial update semantics) | ✅ FIXED | 4ccce99 |
| `list_source_sync_runs` bypassed DI session (raw AsyncSessionLocal) | ✅ FIXED | 4ccce99 |
| `list_source_documents` missing `response_model` (unvalidated dict) | ✅ FIXED | 4ccce99 |
| `/lookup` and `/me/sources` routes registered before `/{user_id}` catch-all | ✅ FIXED | 4ccce99 |
| `DocumentListResponse` / `DocumentResponse` schemas added | ✅ FIXED | 4ccce99 |
| `guardrail_input` short-circuit conditional edge (was unconditional edge) | ✅ FIXED | 366a0d3 |
| `sources`/token fields missing from all `initial_state` dicts | ✅ FIXED | 366a0d3 |
| `pipeline` Factory missing `db_session` and `langfuse` (would crash at runtime) | ✅ FIXED | 366a0d3 |
| `rule_text` sanitized to prevent `</POLICY>` tag injection | ✅ FIXED | latest |
| `AsyncSession(bind=engine)` → `AsyncSessionLocal()` in pipeline factory | ✅ FIXED | latest |
| Profile page added with sidebar link | ✅ FIXED | 600c2b6 / latest |
| `full_name` added to `AuthUser` TypeScript interface | ✅ FIXED | latest |

### Phase F & G Fixes (2026-04-15)

**Phase F — Backend (commits 9748e94, 68300bd)**

| Issue | Status | Notes |
|---|---|---|
| C3 — SQL injection via f-string in database_connector.py | ✅ RESOLVED | `_validate_query()` added using sqlparse; blocks DDL/DML, multi-statements, UNION/INTERSECT/EXCEPT set operations, semicolons |
| CRITICAL-4 — BaseRepository receives sessionmaker not AsyncSession | ✅ RESOLVED | `providers.Factory(lambda: AsyncSessionLocal)` → `providers.Factory(AsyncSessionLocal)`; `session_factory_provider` added for SyncJobService |
| Guardrail events silently discarded | ✅ RESOLVED | Migration 0017, `GuardrailEvent` ORM model, `GuardrailEventRepository`, container wired; `guardrail_service` changed Singleton→Factory |
| guardrail_event_repository flush() never committed | ✅ RESOLVED | Changed to `commit()` with `finally: close()` to return connection to pool |
| Empty guardrail reason stored as "" not NULL | ✅ RESOLVED | `decision.reason or None` normalization in guardrail_service |

**Phase G — Frontend (commits 796a0c2, 68300bd)**

| Issue | Status | Notes |
|---|---|---|
| /admin/analytics page missing | ✅ RESOLVED | Created `admin/analytics/page.tsx` reusing all 5 analytics components |
| Connectors API client missing | ✅ RESOLVED | Created `frontend/src/lib/api/connectors.ts` with list/delete/test functions |
| Permissions list shows raw UUIDs | ✅ RESOLVED | `GET /admin/users/{user_id}` backend endpoint added; `getUserByIdApi` frontend function; PermissionsManager resolves UUIDs to emails via useEffect |
| All frontend API paths missing /api/v1 prefix | ✅ RESOLVED | Fixed in sources.ts, users.ts, connectors.ts, PermissionsManager |

### Remaining Open Issues

| # | Issue | Priority | Notes |
|---|---|---|---|
| M1 | PostgreSQL connector may leak credentials in error messages | P2 | |
| M3 | Encryption key stored as env var, no rotation | P2 | Requires secrets vault infrastructure |
| M5 | pgvector missing `ef_search` parameter | P2 | |
| M6 | Chunks have no soft delete | P2 | |
| M7 | Sources table missing spec columns | P2 | |
| M9 | No token budget management before LLM call | P2 | |
| M10–M17 | Various UX polish items | P2–P3 | |
| L1–L10 | Backlog items | P3 | |

---

*Original report generated: 2026-04-13 | Last updated: 2026-04-15 after Phases F–G remediation on `develop` branch.*
