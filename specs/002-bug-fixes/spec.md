# Feature Specification: 002 — Bug Fixes (Middleware, Pipeline DI, JWT, Security)

**Feature Branch**: `002-bug-fixes`
**Created**: 2026-02-25
**Status**: Draft
**Short Name**: `bug-fixes`
**Priority Mix**: P0 × 2 · P1 × 1 · P2 × 3 · P3 × 3
**Source Audit**: [`specs/bug-fixes/plan.md`](../bug-fixes/plan.md)

<!--
  ============================================================================
  CONSTITUTION ARTICLE IX COMPLIANCE: GATE COMPLIANCE (Directive 4)

  Station 01 (Discovery): This is an internal engineering task, not a user-facing
  feature. ICP/Wedge/JTBD are adapted for developer/ops audience.
  Station 02 (PRD): MVP scope is explicit. All FRs have testable ACs.
  SaaS Rules: single_tenant system — tenancy/billing/limits N/A for this fix set.
  Station 03 (User Flows): No new user flows introduced; fixes restore existing flows.
  ============================================================================
-->

## User Scenarios & Testing _(mandatory)_

**Who is affected:** Backend developers, frontend developers, and end users of the chat interface.

**JTBD (Jobs To Be Done):**
- Developer needs the backend to start without `TypeError` on every chat request [B-PIPE — P0]
- End user needs to reach `/login` without hitting a redirect loop [B-10 — P0]
- End user needs their JWT to contain `email` so the frontend can display it [B-11 — P1]
- Developer needs dead/insecure security functions removed before they are accidentally wired [B-07 — P2]
- Developer needs middleware to only protect routes that actually exist [B-10b — P2]
- Ops needs the DI container to resolve without `BindingNotFound` at startup [B-05 — P2]
- Developer needs no dead code confusing the pipeline module [B-12 — P3]
- Ops needs request logs to appear (middleware must be registered) [B-02 — P3]
- Developer needs the token repository name to reflect its dual purpose [B-09 — P3]

---

### User Story 1 — Pipeline DI Crash (Priority: P0)

Every chat request crashes with `TypeError: build_pipeline() missing required positional arguments` because `container.py` wires the factory without passing `db_session` and `langfuse`. No user can use the chat feature until this is fixed.

**Why this priority**: Application is non-functional for its primary use case.

**Independent Test**: POST to `/api/v1/chat` returns 200 (or a semantic error) rather than a 500 `TypeError`.

**Acceptance Scenarios**:

1. **Given** the DI container wires `build_pipeline()`, **When** a chat request arrives, **Then** `build_pipeline()` receives `db_session` and `langfuse` from registered providers and completes without `TypeError`
2. **Given** `db_session` is a valid SQLAlchemy session, **When** `build_pipeline()` is invoked, **Then** all 8 pipeline nodes initialise successfully

---

### User Story 2 — Auth Middleware Redirect Loop (Priority: P0)

An unauthenticated visitor navigating to `/login` is caught in an infinite redirect loop because the middleware regex checks for `/auth/login` while Next.js App Router strips the `/auth/` prefix from pathnames at runtime.

**Why this priority**: New users cannot log in at all; the application is inaccessible.

**Independent Test**: Open `/login` in a browser with no session cookie — page loads (HTTP 200), no redirect occurs.

**Acceptance Scenarios**:

1. **Given** an unauthenticated browser session, **When** the user navigates to `/login`, **Then** the middleware allows the request through and the login page renders (no redirect loop, no 404)
2. **Given** an unauthenticated browser session, **When** the user navigates to `/register` or `/forgot-password`, **Then** those pages also render without redirect

---

### User Story 3 — JWT Missing `email` Field (Priority: P1)

After a successful login the frontend decodes the access token and finds neither `email` nor `must_change_password`, causing `undefined` to appear in the UI wherever user identity is displayed.

**Why this priority**: Auth succeeds but the UI is broken for all authenticated users.

**Independent Test**: Decode the JWT returned by `/api/v1/auth/login` — `payload.email` is a non-empty string and `payload.must_change_password` is a boolean.

**Acceptance Scenarios**:

1. **Given** valid credentials are submitted to `/api/v1/auth/login`, **When** the access token is decoded, **Then** the payload contains `email` (string) and `must_change_password` (boolean)
2. **Given** the token payload is available in the frontend, **When** the user profile header renders, **Then** `email` is displayed correctly without `undefined`

---

### User Story 4 — Dead / Insecure Security Functions (Priority: P2)

`security.py` contains `create_refresh_token` and `verify_refresh_token` which generate UUID tokens and compare them without hashing — a security vulnerability if accidentally wired.

**Why this priority**: Not yet wired, but deletion reduces attack surface and removes confusion.

**Independent Test**: `grep -r "create_refresh_token\|verify_refresh_token" backend/src/` returns no results.

**Acceptance Scenarios**:

1. **Given** `backend/src/core/security.py` is reviewed, **When** searching for `create_refresh_token` or `verify_refresh_token`, **Then** neither function exists in the file
2. **Given** the functions are removed, **When** the test suite runs, **Then** no existing test imports or calls those functions

---

### User Story 5 — Invalid Dashboard Route Regex (Priority: P2)

`DASHBOARD_ROUTES` in `middleware.ts` lists `sources` and `profile` which do not exist as App Router pages, causing middleware to attempt to protect non-existent routes.

**Why this priority**: Causes incorrect auth redirects for any path that happens to match the stale pattern.

**Independent Test**: Review `DASHBOARD_ROUTES` constant — only `/dashboard`, `/chat`, `/settings`, `/admin` are listed.

**Acceptance Scenarios**:

1. **Given** `DASHBOARD_ROUTES` regex is evaluated, **When** checking which paths require authentication, **Then** only real App Router routes are listed; `sources` and `profile` are absent

---

### User Story 6 — Missing Worker Health DI Provider (Priority: P2)

`container.py` references `worker_health_service` but no provider is registered, causing `BindingNotFound` at application startup and preventing the container from wiring.

**Why this priority**: Application fails to start; affects all environments.

**Independent Test**: `docker-compose up` completes; no `BindingNotFound` in container logs.

**Acceptance Scenarios**:

1. **Given** the DI container in `container.py` is initialised, **When** the container is fully wired at application startup, **Then** `worker_health_service` resolves without `BindingNotFound` or `AttributeError`

---

### User Story 7 — Dead `run_pipeline()` Wrapper (Priority: P3)

`pipeline.py` contains a `run_pipeline()` function that is never called. It creates confusion about entry points.

**Why this priority**: Code quality / maintainability; no runtime impact.

**Independent Test**: `grep -r "run_pipeline" backend/src/` returns no results.

**Acceptance Scenarios**:

1. **Given** `backend/src/agent/pipeline.py` is reviewed, **When** searching for `run_pipeline`, **Then** the function does not exist in the module

---

### User Story 8 — Logging Middleware Not Registered (Priority: P3)

`LoggingMiddleware` is defined in `main.py` but never passed to `app.add_middleware()`, so no request logs are emitted.

**Why this priority**: Observability gap; no runtime crash but debugging is impaired.

**Independent Test**: Send one request after applying the fix — a structured log line appears in stdout.

**Acceptance Scenarios**:

1. **Given** the FastAPI app starts in `main.py`, **When** any request is processed, **Then** a structured log entry for that request appears in stdout

---

### User Story 9 — Misleading Repository Name (Priority: P3)

`RefreshTokenRepository` handles both access and refresh tokens. The misleading name makes the codebase harder to navigate.

**Why this priority**: Developer experience / maintainability; no runtime impact.

**Independent Test**: `grep -r "RefreshTokenRepository" backend/src/` returns no results; `grep -r "TokenRepository" backend/src/` shows all import sites updated.

**Acceptance Scenarios**:

1. **Given** `backend/src/repositories/` is reviewed, **When** looking for the token repository, **Then** the file and class are named `TokenRepository`; all import sites are updated accordingly

---

### Edge Cases

- What if `db_session` is `None` when passed to `build_pipeline()`? → The container MUST always inject a valid session from a scoped provider; no `None` fallback is acceptable.
- What if a future developer adds a route to `DASHBOARD_ROUTES` before creating its page? → Developer checklist item: create the App Router page file first, then add it to the regex.
- What if `WorkerHealthService` itself has a dependency that is also unregistered? → B-05 fix scope is registration only; if further `BindingNotFound` errors surface they must be addressed as follow-on bugs.
- Can `LoggingMiddleware` registration order affect other middleware (e.g., CORS, auth)? → Register `LoggingMiddleware` last (outermost) so it wraps all other middleware and logs the final request/response.

## Requirements _(mandatory)_

<!-- Station 02 satisfied: MVP scope is all 9 bugs; Non-goal is any new feature work.
     SaaS Rules: single_tenant — tenancy boundary, billing, and limits are N/A for this fix set.
     RBAC: fixes apply uniformly across all roles; no permission model changes. -->

### Functional Requirements

- **FR-001**: `build_pipeline()` MUST accept `db_session` and `langfuse` as positional/keyword parameters; `container.py` MUST pass them from registered providers when wiring the pipeline factory
- **FR-002**: `PUBLIC_ROUTES` in `frontend/src/middleware.ts` MUST match App Router pathnames without the `/auth/` prefix (i.e., `/login`, `/register`, `/forgot-password`)
- **FR-003**: The JWT access token payload created in `backend/src/services/auth_service.py` MUST include `email` (str) and `must_change_password` (bool) claims
- **FR-004**: `backend/src/core/security.py` MUST NOT contain `create_refresh_token()` or `verify_refresh_token()` functions; any callers MUST be updated to use the correct JWT-based helpers
- **FR-005**: `DASHBOARD_ROUTES` regex in `frontend/src/middleware.ts` MUST reference only routes that exist in the Next.js App Router page tree (`/dashboard`, `/chat`, `/settings`, `/admin`)
- **FR-006**: `backend/src/core/container.py` MUST register a provider for `worker_health_service` that resolves `WorkerHealthService`
- **FR-007**: `backend/src/agent/pipeline.py` MUST NOT contain the dead `run_pipeline()` wrapper function
- **FR-008**: `LoggingMiddleware` MUST be registered via `app.add_middleware(LoggingMiddleware)` in `backend/src/main.py` before the application starts accepting requests
- **FR-009**: The token repository MUST be renamed `TokenRepository` in both filename (`token_repository.py`) and class definition; all import sites across the backend MUST be updated

### Key Entities

- **No new entities.** No schema migrations, no new database models. All changes are code-only (logic, wiring, naming).
- **Affected modules** (for traceability, not new entities):
  - `backend/src/agent/pipeline.py` — B-PIPE, B-12
  - `backend/src/core/container.py` — B-PIPE, B-05
  - `frontend/src/middleware.ts` — B-10, B-10b
  - `backend/src/services/auth_service.py` — B-11
  - `backend/src/core/security.py` — B-07
  - `backend/src/main.py` — B-02
  - `backend/src/repositories/refresh_token_repository.py` → `token_repository.py` — B-09

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: `pytest` backend test suite passes with 0 failures after all 9 fixes are applied
- **SC-002**: POST to `/api/v1/chat` completes without `TypeError: build_pipeline() missing required positional arguments`
- **SC-003**: GET `/login` by an unauthenticated browser session returns HTTP 200 with no redirect loop and no 404
- **SC-004**: JWT payload decoded after POST `/api/v1/auth/login` contains both `email` (non-empty string) and `must_change_password` (boolean) keys
- **SC-005**: `docker-compose up` completes with all 9 services in `healthy` state — no container exits or crashes due to DI `BindingNotFound` errors at startup

### Assumptions

- `WorkerHealthService` class already exists in the codebase; only its DI provider registration is missing (B-05)
- No LangGraph pipeline node logic is altered — only the argument wiring in `container.py` (B-PIPE)
- No database schema changes are required for any of the 9 fixes
- The Next.js App Router page tree currently contains exactly: `/login`, `/register`, `/forgot-password`, `/dashboard`, `/chat`, `/settings`, `/admin`
- No external API contracts or client SDKs depend on the current token repository class name

### Dependencies

- [`specs/bug-fixes/plan.md`](../bug-fixes/plan.md) — source audit document containing exact before/after diffs for all 9 bugs
- `backend/src/core/container.py` — central DI container; affected by B-PIPE and B-05
- `backend/src/agent/pipeline.py` — affected by B-PIPE and B-12
- `frontend/src/middleware.ts` — affected by B-10 and B-10b
- `backend/src/services/auth_service.py` — affected by B-11
- `backend/src/core/security.py` — affected by B-07
- `backend/src/main.py` — affected by B-02
- `backend/src/repositories/refresh_token_repository.py` — affected by B-09 (rename to `token_repository.py`)
- **SC-004**: [Business metric, e.g., "Reduce support tickets related to [X] by 50%"]
