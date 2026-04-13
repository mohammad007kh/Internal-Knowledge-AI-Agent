# Bug Fix Plan — "Fix Everything"

**Status:** Ready for implementation  
**Audit coverage:** security.py, auth_service.py, deps.py, auth.py, container.py, main.py, pipeline.py (all 135 lines), chat.py (all 285 lines), refresh_token_repository.py (all 132 lines), middleware.ts, api-client.ts, auth.ts, AuthContext.tsx, sources.py (80/243 lines), plus directory listings for all major folders.  
**Closed false positives:** B-01 (api-client redirect), B-08 (SHA-256 hashing confirmed correct).

---

## Risk Matrix

| ID | Priority | Category | Impact |
|---|---|---|---|
| [B-10](#b-10--p0--middleware-auth-routes-regex--redirects-are-broken) | **P0** | Routing | Every unauthenticated user hits a 404 instead of the login page. Entire app is unreachable to new/logged-out users. |
| [B-PIPE](#b-pipe--p0--pipeline-factory-missing-two-required-arguments) | **P0** | DI wiring | Every chat message request crashes with `TypeError`. The chat feature is entirely non-functional. |
| [B-11](#b-11--p1--jwt-payload-missing-email-and-must_change_password) | **P1** | Auth | `user.email` is always `undefined` in the frontend; the forced-password-change guard never fires. Silent feature breakage. |
| [B-07](#b-07--p2--dead-and-insecure-code-in-securitypy) | **P2** | Security | Two dead functions in `security.py` use unsalted UUID token generation and an unhashed DB lookup. If ever called, they create a security vulnerability. |
| [B-10b](#b-10b--p2--dashboard-route-regex-lists-nonexistent-paths) | **P2** | Routing | Middleware protects `sources` and `profile` paths that don't exist; any future route with those names won't need an explicit guard update but this is a silent contract mismatch. |
| [B-05](#b-05--p2--worker_health_service-provider-missing-from-container) | **P2** | DI wiring | `worker_health_service` is referenced (Celery health check) but has no provider. Any endpoint that resolves it will crash. |
| [B-12](#b-12--p3--run_pipeline-is-dead-code) | **P3** | Cleanup | `run_pipeline()` in `pipeline.py` is a dead wrapper never called by the app. |
| [B-02](#b-02--p3--logging-middleware-exists-but-is-never-registered) | **P3** | Cleanup | `logging_middleware.py` was written but never imported or mounted in `main.py`. |
| [B-09](#b-09--p3--naming-mismatch-in-refresh-token-repository) | **P3** | Clarity | `RefreshTokenRepository` also handles password-reset tokens. The name is misleading. |

---

## P0 — App Non-Functional

### B-10 · P0 · Middleware auth-route regex & redirects are broken

#### Root cause

`frontend/src/middleware.ts` was written assuming the Next.js App Router route groups `(auth)` and `(dashboard)` produce URL prefixes. They do not — parenthesised route group folders are stripped from the URL. As a result:

| Code | Assumed URL | Actual URL |
|---|---|---|
| `AUTH_ROUTES = /^\/auth(\/\|$)/` | `/auth/login`, `/auth/setup` | `/login`, `/setup` (no `/auth/`) |
| `redirect('/auth/login')` | redirect target exists | redirect target → **404** |
| `CHANGE_PASSWORD_ROUTE = '/auth/change-password'` | page exists at that path | page exists at `/change-password` |

Because `AUTH_ROUTES` never matches (the real paths are `/login`, `/change-password`, etc.), the middleware does **not** recognise the login page as a public route. Unauthenticated users are redirected to `/auth/login` (404) in an infinite redirect loop.

#### Exact fix — `frontend/src/middleware.ts`

```diff
-const AUTH_ROUTES = /^\/auth(\/|$)/;
+const AUTH_ROUTES = /^\/(login|change-password|password-reset|setup)(\/|$)/;

-const CHANGE_PASSWORD_ROUTE = '/auth/change-password';
+const CHANGE_PASSWORD_ROUTE = '/change-password';

-  return NextResponse.redirect(new URL('/auth/login', request.url));
+  return NextResponse.redirect(new URL('/login', request.url));
```

#### Verification

1. Unauthenticated `GET /chat` → 302 → `/login` (not 404).  
2. Authenticated `GET /login` → 302 → `/` (dashboard).  
3. Authenticated user with `must_change_password=true` + `GET /chat` → 302 → `/change-password`.  
4. `GET /login` (unauthenticated) → 200, no redirect loop.

---

### B-PIPE · P0 · Pipeline factory missing two required arguments

#### Root cause

`build_pipeline()` in `backend/src/agent/pipeline.py` declares two **required** keyword-only parameters that have **no default value**:

```python
def build_pipeline(
    *,
    db_session: AsyncSession,   # ← REQUIRED, no default
    ...
    langfuse: Langfuse,         # ← REQUIRED, no default
) -> CompiledStateGraph:
```

Both are baked into `functools.partial` calls for the `load_history`, `retrieve_context`, and `save_message` nodes.

The container factory in `backend/src/core/container.py` omits **both**:

```python
pipeline = providers.Factory(
    build_pipeline,
    embedding_service=embedding_service,
    chunk_repository=chunk_repo,
    chat_session_repository=chat_session_repo,
    chat_message_repository=chat_message_repo,
    openai_client=openai_client,
    # ❌ langfuse not passed
    # ❌ db_session not passed
)
```

`_get_pipeline()` in `chat.py` calls `Container.pipeline()` with zero extra arguments. Every call raises:

```
TypeError: build_pipeline() missing 1 required keyword-only argument: 'db_session'
```

(Assuming dependency-injector raises on the first missing arg; `langfuse` would be the second.)

#### Two-part fix

**Part 1 — `langfuse` (simple, one line)**

Add `langfuse` to the factory in `container.py`:

```diff
 pipeline = providers.Factory(
     build_pipeline,
     embedding_service=embedding_service,
     chunk_repository=chunk_repo,
     chat_session_repository=chat_session_repo,
     chat_message_repository=chat_message_repo,
     openai_client=openai_client,
+    langfuse=langfuse,
 )
```

**Part 2 — `db_session` (architectural, requires node changes)**

Baking a single `AsyncSession` into a compiled graph at factory time is wrong: the graph is reused across requests but a SQLAlchemy `AsyncSession` is request-scoped. The correct pattern is to pass a **session factory** (the `AsyncSessionLocal` callable) into the nodes that need DB access, and have each node open and close its own session.

*Step 1* — Change `build_pipeline` signature:

```diff
 def build_pipeline(
     *,
-    db_session: AsyncSession,
+    session_factory: async_sessionmaker,
     embedding_service: EmbeddingService,
     chunk_repository: ChunkRepository,
     chat_session_repository: ChatSessionRepository,
     chat_message_repository: ChatMessageRepository,
     openai_client: AsyncOpenAI,
     langfuse: Langfuse,
 ) -> CompiledStateGraph:
```

*Step 2* — Update the three affected partial bindings inside `build_pipeline`:

```diff
-_load_history = functools.partial(
-    load_history,
-    chat_session_repository=chat_session_repository,
-    chat_message_repository=chat_message_repository,
-    db_session=db_session,
-)
+_load_history = functools.partial(
+    load_history,
+    chat_session_repository=chat_session_repository,
+    chat_message_repository=chat_message_repository,
+    session_factory=session_factory,
+)
 
-_retrieve_context = functools.partial(
-    retrieve_context,
-    embedding_service=embedding_service,
-    chunk_repository=chunk_repository,
-    db_session=db_session,
-    langfuse=langfuse,
-)
+_retrieve_context = functools.partial(
+    retrieve_context,
+    embedding_service=embedding_service,
+    chunk_repository=chunk_repository,
+    session_factory=session_factory,
+    langfuse=langfuse,
+)
 
-_save_message = functools.partial(
-    save_message,
-    chat_session_repository=chat_session_repository,
-    chat_message_repository=chat_message_repository,
-    db_session=db_session,
-)
+_save_message = functools.partial(
+    save_message,
+    chat_session_repository=chat_session_repository,
+    chat_message_repository=chat_message_repository,
+    session_factory=session_factory,
+)
```

*Step 3* — Update each of the three node implementations (`load_history.py`, `retrieve_context.py`, `save_message.py`) to accept `session_factory: async_sessionmaker` and use a context-managed session internally:

```python
# Pattern for each node
async def load_history(state: AgentState, *, ..., session_factory: async_sessionmaker) -> AgentState:
    async with session_factory() as db:
        # ... use db (AsyncSession) here
```

*Step 4* — Wire `session_factory` into the container factory. The container already has `db_session_factory` which resolves to `AsyncSessionLocal`. Update the pipeline factory:

```diff
 pipeline = providers.Factory(
     build_pipeline,
+    session_factory=db_session_factory,
     embedding_service=embedding_service,
     chunk_repository=chunk_repo,
     chat_session_repository=chat_session_repo,
     chat_message_repository=chat_message_repo,
     openai_client=openai_client,
     langfuse=langfuse,
 )
```

> **Note:** `db_session_factory` in the container currently resolves to `lambda: AsyncSessionLocal` (a `providers.Factory` that returns the class). Confirm it is `async_sessionmaker` / `AsyncSessionLocal` (the sessionmaker, not the raw class). If it is a bare class rather than a callable sessionmaker, replace `providers.Factory(lambda: AsyncSessionLocal)` with `providers.Object(AsyncSessionLocal)` so the provider returns the sessionmaker directly.

#### Verification

1. `Container.pipeline()` resolves without `TypeError`.  
2. `POST /api/v1/chat/sessions/{id}/messages` returns SSE events instead of 500.  
3. `load_history`, `retrieve_context`, `save_message` each open and close a session per node invocation.  
4. Langfuse trace appears in Langfuse dashboard for a test chat request.  
5. Concurrent chat requests do not share a session.

---

## P1 — Silent Feature Breakage

### B-11 · P1 · JWT payload missing `email` and `must_change_password`

#### Root cause

`AuthContext.tsx` decodes the JWT and reads `payload.email` and `payload.must_change_password`:

```ts
// frontend/src/features/auth/context/AuthContext.tsx
interface JwtPayload {
  sub: string;
  email: string;               // ← expected in token
  role: string;
  must_change_password?: boolean;  // ← drives forced-change redirect
  exp: number;
}
```

`create_access_token()` in `security.py` is called in `auth_service.py._issue_tokens()` with only `{"sub": user_id, "role": user.role}`. Neither `email` nor `must_change_password` is included. As a result:

- `user.email` is always `undefined` everywhere in the React app.  
- The password-change guard (`if (user.must_change_password) router.push('/change-password')`) never fires — users who must change their password can continue using the app with full access.

#### Exact fix — `backend/src/services/auth_service.py`

Locate the `_issue_tokens` method (or wherever `create_access_token` is called) and extend the payload:

```diff
 access_token = create_access_token({
     "sub": str(user.id),
     "role": user.role.value,
+    "email": user.email,
+    "must_change_password": user.must_change_password,
 })
```

No changes to `security.py` or the frontend are needed — the frontend already reads these fields.

#### Verification

1. After login, decode the returned JWT (e.g., jwt.io) and confirm `email` and `must_change_password` fields are present.  
2. In the React app, `useAuth().user.email` returns the correct email string.  
3. A user with `must_change_password=true` is redirected to `/change-password` on next login.  
4. A user with `must_change_password=false` is not redirected.

---

## P2 — Broken Wiring and Security Risks

### B-07 · P2 · Dead and insecure code in `security.py`

#### Root cause

`backend/src/core/security.py` contains two functions that are **never called** by any live code path but would create a security vulnerability if called:

```python
def create_refresh_token() -> str:
    return str(uuid.uuid4())        # UUID v4, not secrets.token_urlsafe — weaker entropy,
                                    # and not the format used anywhere in the real flow

def verify_refresh_token(token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(token, stored_hash)  # compares plaintext to hash — always False
                                                     # and leaks that hashing is expected
```

The real token generation (`secrets.token_urlsafe(32)`) and real hash verification (`_hash_token()` + SHA-256 DB lookup) all live in `auth_service.py` and `refresh_token_repository.py`. These two functions in `security.py` are orphaned leftovers from an earlier design.

#### Exact fix — `backend/src/core/security.py`

Delete both functions entirely:

```diff
-def create_refresh_token() -> str:
-    return str(uuid.uuid4())
-
-def verify_refresh_token(token: str, stored_hash: str) -> bool:
-    return hmac.compare_digest(token, stored_hash)
```

Grep the codebase to confirm no caller exists before deleting:

```bash
grep -r "create_refresh_token\|verify_refresh_token" backend/src
```

Expected output: zero results (other than the definitions themselves).

#### Verification

1. No import errors after deletion.  
2. All refresh-token tests pass (they should use the `auth_service` path, not these functions).

---

### B-10b · P2 · Dashboard route regex lists nonexistent paths

#### Root cause

`DASHBOARD_ROUTES` in `middleware.ts` includes `sources` and `profile`:

```ts
const DASHBOARD_ROUTES = /^\/(chat|admin|sources|profile)(\/|$)/;
```

The `app/(dashboard)/` directory contains only `admin/`, `chat/`, `layout.tsx`, and `page.tsx`. There is no `sources/` or `profile/` directory. These paths currently return 404. More critically, if a future developer adds these routes, the middleware guard will activate with whatever behaviour was originally intended — without any deliberate decision being made.

#### Fix — `frontend/src/middleware.ts`

**Option A (recommended): Remove nonexistent paths**

```diff
-const DASHBOARD_ROUTES = /^\/(chat|admin|sources|profile)(\/|$)/;
+const DASHBOARD_ROUTES = /^\/(chat|admin)(\/|$)/;
```

**Option B: Create the missing route directories** if `sources` and `profile` pages are planned features, scaffold the directories now so the middleware contract is accurate.

---

### B-05 · P2 · `worker_health_service` provider missing from container

#### Root cause

The `health.py` endpoint (or another caller) references `Container.worker_health_service()` but `container.py` registers no such provider. Calling it raises `AttributeError` or the dependency-injector equivalent.

#### Fix — `backend/src/core/container.py`

If Celery worker health checking is needed, add the provider:

```python
from src.services.worker_health_service import WorkerHealthService

worker_health_service: providers.Singleton[WorkerHealthService] = providers.Singleton(
    WorkerHealthService,
    broker_url=providers.Object(settings.CELERY_BROKER_URL),
)
```

If this feature is out of scope, find and remove all references:

```bash
grep -r "worker_health_service" backend/src
```

Then delete the corresponding service file and endpoint code.

---

## P3 — Cleanup

### B-12 · P3 · `run_pipeline()` is dead code

`backend/src/agent/pipeline.py` contains a `run_pipeline()` wrapper function. `chat.py` calls `pipeline.astream_events(...)` directly. `run_pipeline()` is never called. Delete it. If a canonical helper wrapper is desired, replace it with one that conforms to the `astream_events` pattern used in `chat.py`.

---

### B-02 · P3 · Logging middleware exists but is never registered

`backend/src/api/middleware/logging_middleware.py` was written but is not imported or mounted in `backend/src/main.py`. Either:

**Register it:**
```python
# backend/src/main.py
from src.api.middleware.logging_middleware import LoggingMiddleware
app.add_middleware(LoggingMiddleware)
```

**Or delete it** if structured logging is being handled elsewhere (Sentry, uvicorn access log, etc.).

---

### B-09 · P3 · Naming mismatch — `RefreshTokenRepository` handles two token types

`backend/src/repositories/refresh_token_repository.py` stores and validates both **refresh tokens** (for session continuation) and **password-reset tokens** (for the reset flow). The class name `RefreshTokenRepository` misrepresents its scope and makes the code harder to reason about.

Rename throughout:

| Old | New |
|---|---|
| `RefreshTokenRepository` | `TokenRepository` |
| `refresh_token_repo` (container) | `token_repo` |
| `_refresh_token_repo` (auth_service) | `_token_repo` |
| `refresh_token_repository.py` | `token_repository.py` |

---

## Implementation Sequence

Execute in this order to minimise debugging complexity:

```
1. B-10   — middleware.ts regex + redirects         (5 min, no backend changes)
2. B-11   — auth_service.py JWT payload             (5 min, no schema changes)
3. B-PIPE — container.py langfuse wire-up           (2 min, Part 1 of pipeline fix)
4. B-PIPE — pipeline.py + node files session refactor  (30–60 min, Part 2)
5. B-07   — delete dead security.py functions       (5 min)
6. B-10b  — clean up DASHBOARD_ROUTES regex         (2 min)
7. B-05   — add or remove worker_health_service     (15 min, depends on product decision)
8. B-12   — delete run_pipeline()                   (2 min)
9. B-02   — register or delete logging_middleware   (5 min)
10. B-09  — rename RefreshTokenRepository           (10 min, grep + replace)
```

**Total estimated effort:** ~2–3 hours for a developer familiar with the codebase.

---

## Full Test Checklist

### After B-10
- [ ] Unauthenticated `GET /chat` → `302 /login`
- [ ] `GET /login` (unauthenticated) → `200`, no redirect loop
- [ ] Authenticated `GET /login` → `302 /` (dashboard)
- [ ] Authenticated user with `must_change_password=true` → `302 /change-password`

### After B-PIPE
- [ ] `Container.pipeline()` resolves without `TypeError`
- [ ] `POST /api/v1/chat/sessions/{id}/messages` returns SSE stream
- [ ] Langfuse trace visible in dashboard for test chat request
- [ ] Multiple concurrent chat sessions don't share a DB session

### After B-11
- [ ] JWT payload contains `email`, `role`, `must_change_password`, `sub`, `exp`
- [ ] `useAuth().user.email` matches the logged-in user's email
- [ ] User with `must_change_password=true` is redirected after login

### After B-07
- [ ] `grep -r "create_refresh_token\|verify_refresh_token" backend/src` → zero results
- [ ] All auth tests pass

### After B-05
- [ ] `GET /api/v1/health` (or equivalent) returns 200
- [ ] No `AttributeError` on `Container.worker_health_service`

### Regression suite
- [ ] Full pytest run — `backend/` — zero failures
- [ ] Frontend build — `next build` — zero errors
- [ ] E2E: full login → chat → logout flow
