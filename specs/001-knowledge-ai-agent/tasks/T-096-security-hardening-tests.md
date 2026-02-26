# T-096 · Security Hardening — Headers, Rate Limiting & RBAC Smoke Tests

**Phase:** 9 — Testing, Polish & SC Verification  
**Depends on:** T-091 (integration test stack running)  
**Blocks:** T-099

---

## Context

```
Python 3.12 | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector
Next.js 15 App Router · shadcn/ui · Tailwind CSS v4
React Context · TanStack Query v5 · react-hook-form · Zod
PostgreSQL 16 + pgvector · HNSW m=16 ef_construction=64 · UUID PKs · soft-delete + audit columns
Alembic versioned migrations
Celery + Redis · Beat replicas=1 STRICT
MinIO · presigned PUT pattern
JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user)
Fernet (connection configs + LLM API keys at rest)
LangGraph 8-node · interrupt() for clarification · SSE streaming
Langfuse self-hosted · every pipeline run must emit a trace
RFC 7807 Problem Details — all non-2xx API responses
Structured logging · INFO level · X-Request-ID correlation
CORS strict · CSRF SameSite=Strict httpOnly · CSP moderate · rate-limit IP
Dark mode · responsive · WCAG-AA · no animations · Lucide icons · Sonner toasts
snake_case vars/files/tables · PascalCase classes · SCREAMING_SNAKE_CASE constants
pytest + httpx + Playwright · ≥80% coverage
Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db
```

---

## Objective

Verify the security posture across three categories:

1. **HTTP security headers** — CSP, HSTS, X-Content-Type-Options, X-Frame-Options, etc.  
2. **Rate limiting** — IP-based 429 responses after threshold exceeded  
3. **RBAC smoke tests** — every protected endpoint correctly rejects `user` role / unauthenticated callers

File location:

- `tests/integration/security/test_security_headers.py`
- `tests/integration/security/test_rate_limiting.py`
- `tests/integration/security/test_rbac_smoke.py`

---

## 1. Security Headers Tests — `tests/integration/security/test_security_headers.py`

```python
"""
Security-header verification.

All assertions run against the /api/v1/health endpoint (no auth required)
so the tests are fast and do not depend on a seeded database.
"""
import pytest
from httpx import AsyncClient


PROBE_URL = "/api/v1/health"


@pytest.mark.asyncio
async def test_x_content_type_options_header(async_client: AsyncClient) -> None:
    r = await async_client.get(PROBE_URL)
    assert r.headers.get("x-content-type-options") == "nosniff"


@pytest.mark.asyncio
async def test_x_frame_options_header(async_client: AsyncClient) -> None:
    r = await async_client.get(PROBE_URL)
    val = r.headers.get("x-frame-options", "").lower()
    assert val in ("deny", "sameorigin"), f"Unexpected X-Frame-Options: {val}"


@pytest.mark.asyncio
async def test_strict_transport_security_header(async_client: AsyncClient) -> None:
    """HSTS must be present with max-age ≥ one year (31 536 000 s)."""
    r = await async_client.get(PROBE_URL)
    hsts = r.headers.get("strict-transport-security", "")
    assert hsts, "HSTS header missing"
    # Extract max-age value
    parts = {kv.strip().split("=")[0].lower(): kv.strip().split("=")[1]
             for kv in hsts.split(";") if "=" in kv}
    max_age = int(parts.get("max-age", 0))
    assert max_age >= 31_536_000, f"HSTS max-age too small: {max_age}"


@pytest.mark.asyncio
async def test_content_security_policy_present(async_client: AsyncClient) -> None:
    r = await async_client.get(PROBE_URL)
    csp = r.headers.get("content-security-policy", "")
    assert csp, "CSP header missing"
    # Must have at minimum a default-src directive
    assert "default-src" in csp.lower()


@pytest.mark.asyncio
async def test_referrer_policy_header(async_client: AsyncClient) -> None:
    r = await async_client.get(PROBE_URL)
    rp = r.headers.get("referrer-policy", "")
    allowed = {
        "no-referrer",
        "no-referrer-when-downgrade",
        "strict-origin",
        "strict-origin-when-cross-origin",
    }
    assert rp.lower() in allowed, f"Referrer-Policy unexpected: {rp}"


@pytest.mark.asyncio
async def test_no_server_header_or_generic(async_client: AsyncClient) -> None:
    """Server header must be absent or set to a generic value (not 'uvicorn')."""
    r = await async_client.get(PROBE_URL)
    server = r.headers.get("server", "")
    if server:
        assert "uvicorn" not in server.lower(), f"Uvicorn version leaked in Server: {server}"
        assert "python" not in server.lower()


@pytest.mark.asyncio
async def test_permissions_policy_header(async_client: AsyncClient) -> None:
    r = await async_client.get(PROBE_URL)
    pp = r.headers.get("permissions-policy", "")
    # At minimum camera, microphone, geolocation should be restricted
    assert pp, "Permissions-Policy header missing"
    assert "camera" in pp
    assert "microphone" in pp


@pytest.mark.asyncio
async def test_cors_rejects_arbitrary_origin(async_client: AsyncClient) -> None:
    r = await async_client.get(
        "/api/v1/health",
        headers={"Origin": "https://evil.example.com"},
    )
    acao = r.headers.get("access-control-allow-origin", "")
    assert acao != "*", "CORS allows all origins"
    assert "evil.example.com" not in acao


@pytest.mark.asyncio
async def test_cors_allows_whitelisted_origin(async_client: AsyncClient) -> None:
    """Whitelisted frontend origin must be reflected in CORS header."""
    import os
    allowed = os.environ.get("ALLOWED_ORIGIN", "http://localhost:3000")
    r = await async_client.get(
        "/api/v1/health",
        headers={"Origin": allowed},
    )
    acao = r.headers.get("access-control-allow-origin", "")
    assert allowed in acao


@pytest.mark.asyncio
async def test_x_request_id_present_in_response(async_client: AsyncClient) -> None:
    r = await async_client.get(PROBE_URL)
    assert r.headers.get("x-request-id"), "X-Request-ID missing from response"
```

---

## 2. Rate Limiting Tests — `tests/integration/security/test_rate_limiting.py`

```python
"""
IP-based rate limiting (slowapi / starlette-limiter).

The threshold for POST /api/v1/auth/login is configured to 5/minute in tests.
Override via environment variable RATE_LIMIT_LOGIN (default "5/minute").
"""
import asyncio
import pytest
from httpx import AsyncClient

# How many requests trigger the 429 — read from app settings or default
LOGIN_RATE_LIMIT = 5
LOGIN_URL = "/api/v1/auth/login"
BAD_CREDENTIALS = {"email": "nobody@example.com", "password": "wrong"}


@pytest.mark.asyncio
async def test_login_rate_limit_returns_429(async_client: AsyncClient) -> None:
    """Exceed LOGIN_RATE_LIMIT requests → 429 Too Many Requests."""
    for _ in range(LOGIN_RATE_LIMIT):
        await async_client.post(LOGIN_URL, json=BAD_CREDENTIALS)

    # This request should be rate-limited
    r = await async_client.post(LOGIN_URL, json=BAD_CREDENTIALS)
    assert r.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_response_is_rfc7807(async_client: AsyncClient) -> None:
    """429 response must be RFC 7807 Problem Details with type, title, status."""
    for _ in range(LOGIN_RATE_LIMIT + 1):
        r = await async_client.post(LOGIN_URL, json=BAD_CREDENTIALS)

    r = await async_client.post(LOGIN_URL, json=BAD_CREDENTIALS)
    if r.status_code == 429:
        body = r.json()
        assert "type" in body, "RFC 7807: 'type' missing"
        assert "title" in body, "RFC 7807: 'title' missing"
        assert body["status"] == 429


@pytest.mark.asyncio
async def test_429_includes_retry_after_header(async_client: AsyncClient) -> None:
    """Rate-limited response must include Retry-After header."""
    for _ in range(LOGIN_RATE_LIMIT + 1):
        r = await async_client.post(LOGIN_URL, json=BAD_CREDENTIALS)

    r = await async_client.post(LOGIN_URL, json=BAD_CREDENTIALS)
    if r.status_code == 429:
        assert r.headers.get("retry-after"), "Retry-After header missing"


@pytest.mark.asyncio
async def test_read_endpoints_not_rate_limited_at_login_threshold(
    async_client: AsyncClient,
    user_token: str,
) -> None:
    """GET /api/v1/chat/sessions should NOT be blocked at login threshold."""
    headers = {"Authorization": f"Bearer {user_token}"}
    for _ in range(LOGIN_RATE_LIMIT + 2):
        r = await async_client.get("/api/v1/chat/sessions", headers=headers)
        assert r.status_code != 429, (
            f"Read endpoint incorrectly rate-limited at attempt {_+1}"
        )
```

---

## 3. RBAC Smoke Tests — `tests/integration/security/test_rbac_smoke.py`

```python
"""
RBAC smoke tests — every admin endpoint must reject
regular users (403) and unauthenticated callers (401).

Each entry is (method, path).
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Admin-only endpoints
# ---------------------------------------------------------------------------
ADMIN_ONLY_ENDPOINTS: list[tuple[str, str]] = [
    # User management
    ("GET",    "/api/v1/admin/users"),
    ("POST",   "/api/v1/admin/users/invite"),
    ("DELETE", "/api/v1/admin/users/00000000-0000-0000-0000-000000000001"),
    ("PATCH",  "/api/v1/admin/users/00000000-0000-0000-0000-000000000001/role"),
    # Sources
    ("GET",    "/api/v1/sources"),
    ("POST",   "/api/v1/sources"),
    ("DELETE", "/api/v1/sources/00000000-0000-0000-0000-000000000001"),
    ("GET",    "/api/v1/sources/00000000-0000-0000-0000-000000000001/inspect"),
    ("POST",   "/api/v1/sources/00000000-0000-0000-0000-000000000001/approve"),
    # LLM connections
    ("GET",    "/api/v1/connections"),
    ("POST",   "/api/v1/connections"),
    ("DELETE", "/api/v1/connections/00000000-0000-0000-0000-000000000001"),
    # Guardrails
    ("GET",    "/api/v1/guardrails"),
    ("POST",   "/api/v1/guardrails"),
    ("PATCH",  "/api/v1/guardrails/00000000-0000-0000-0000-000000000001"),
    ("DELETE", "/api/v1/guardrails/00000000-0000-0000-0000-000000000001"),
    # Worker health
    ("GET",    "/api/v1/health/workers"),
    # Audit log
    ("GET",    "/api/v1/audit"),
]

# ---------------------------------------------------------------------------
# User-accessible endpoints (user must get 200/201/404, not 403)
# ---------------------------------------------------------------------------
USER_ACCESSIBLE_ENDPOINTS: list[tuple[str, str]] = [
    ("GET",  "/api/v1/chat/sessions"),
    ("POST", "/api/v1/chat/sessions"),
    ("GET",  "/api/v1/me"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", ADMIN_ONLY_ENDPOINTS)
async def test_admin_endpoint_rejects_unauthenticated(
    async_client: AsyncClient,
    method: str,
    path: str,
) -> None:
    r = await async_client.request(method, path)
    assert r.status_code == 401, (
        f"{method} {path}: expected 401, got {r.status_code}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", ADMIN_ONLY_ENDPOINTS)
async def test_admin_endpoint_rejects_regular_user(
    async_client: AsyncClient,
    user_token: str,
    method: str,
    path: str,
) -> None:
    headers = {"Authorization": f"Bearer {user_token}"}
    r = await async_client.request(method, path, headers=headers)
    assert r.status_code == 403, (
        f"{method} {path}: expected 403 for user-role, got {r.status_code}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", USER_ACCESSIBLE_ENDPOINTS)
async def test_user_accessible_endpoint_rejects_unauthenticated(
    async_client: AsyncClient,
    method: str,
    path: str,
) -> None:
    r = await async_client.request(method, path)
    assert r.status_code == 401, (
        f"{method} {path}: unauthenticated should get 401, got {r.status_code}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", USER_ACCESSIBLE_ENDPOINTS)
async def test_user_accessible_endpoint_allows_user_role(
    async_client: AsyncClient,
    user_token: str,
    method: str,
    path: str,
) -> None:
    headers = {"Authorization": f"Bearer {user_token}"}
    r = await async_client.request(method, path, headers=headers)
    # Any of 200, 201, 404 is acceptable — all mean the user got past auth
    assert r.status_code not in (401, 403), (
        f"{method} {path}: user should be allowed, got {r.status_code}"
    )


# ---------------------------------------------------------------------------
# Token tampering tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tampered_jwt_returns_401(async_client: AsyncClient, user_token: str) -> None:
    """Appending garbage to a valid token must return 401."""
    bad_token = user_token + "tampered"
    r = await async_client.get(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {bad_token}"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_expired_jwt_returns_401(async_client: AsyncClient) -> None:
    """A pre-generated expired token must be rejected with 401."""
    # Derived from: jwt.encode({"sub": "user-id", "exp": 1}, "secret", "HS256")
    expired_token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiJ1c2VyLWlkIiwiZXhwIjoxfQ."
        "3etHMqmoFmS1SBWH2PRQVY7JlFWaKl9kVcGlSUjw1S4"
    )
    r = await async_client.get(
        "/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_signing_secret_returns_401(async_client: AsyncClient) -> None:
    """Token signed with wrong secret must return 401."""
    import jwt
    import datetime

    bad_token = jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000001",
         "role": "admin",
         "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=15)},
        "totally-wrong-secret",
        algorithm="HS256",
    )
    r = await async_client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {bad_token}"},
    )
    assert r.status_code == 401
```

---

## Definition of Done

- [ ] All security-header assertions pass against the test app instance
- [ ] CSP, HSTS (≥1 year), X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy present
- [ ] Server header does not leak `uvicorn` or `python`
- [ ] CORS: arbitrary origin rejected; whitelisted origin allowed
- [ ] X-Request-ID header present in every response
- [ ] Login endpoint returns 429 after 5 rapid requests
- [ ] 429 body is RFC 7807 with `type`, `title`, `status=429`
- [ ] 429 response includes `Retry-After` header
- [ ] All 17 admin endpoints return 401 for unauthenticated and 403 for `user` role
- [ ] User-accessible endpoints return 401 for unauthenticated; not 403 for `user` role
- [ ] Tampered, expired, and wrong-secret JWTs all return 401
