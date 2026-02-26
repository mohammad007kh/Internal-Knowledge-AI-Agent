import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from src.middleware.security_headers import (
    SECURITY_HEADERS,
    SecurityHeadersMiddleware,
    _is_csrf_exempt,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _create_test_app(is_https: bool = False) -> FastAPI:
    """Build a minimal FastAPI app with SecurityHeadersMiddleware."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, is_https=is_https)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/data")
    async def get_data():
        return {"data": "test"}

    @app.post("/api/v1/data")
    async def post_data(request: Request):
        return {"created": True}

    @app.put("/api/v1/data")
    async def put_data(request: Request):
        return {"updated": True}

    @app.delete("/api/v1/data")
    async def delete_data(request: Request):
        return {"deleted": True}

    @app.post("/api/v1/auth/login")
    async def login():
        return {"token": "abc"}

    @app.post("/api/v1/auth/refresh")
    async def refresh():
        return {"token": "refreshed"}

    return app


def _transport(app: FastAPI) -> ASGITransport:
    return ASGITransport(app=app)


# ── Security headers tests ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_security_headers_present_on_get():
    """All security headers must appear on every GET response."""
    app = _create_test_app()
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    for header, value in SECURITY_HEADERS.items():
        assert resp.headers.get(header) == value, f"Missing or wrong: {header}"


@pytest.mark.asyncio
async def test_hsts_present_when_https():
    """Strict-Transport-Security header must be set when is_https=True."""
    app = _create_test_app(is_https=True)
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert resp.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains"


@pytest.mark.asyncio
async def test_hsts_absent_when_not_https():
    """Strict-Transport-Security header must NOT be set when is_https=False."""
    app = _create_test_app(is_https=False)
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    assert "Strict-Transport-Security" not in resp.headers


# ── CSRF tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_csrf_blocks_post_without_token():
    """POST to a non-exempt path without CSRF token → 403 problem+json."""
    app = _create_test_app()
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.post("/api/v1/data")

    assert resp.status_code == 403
    assert resp.headers.get("content-type") == "application/problem+json"
    body = resp.json()
    assert body["status"] == 403
    assert body["title"] == "Forbidden"
    assert "CSRF" in body["detail"]


@pytest.mark.asyncio
async def test_csrf_passes_with_matching_token():
    """POST with matching csrf_token cookie and X-CSRF-Token header → success."""
    app = _create_test_app()
    token = "valid-csrf-token-abc123"
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/data",
            headers={"X-CSRF-Token": token},
            cookies={"csrf_token": token},
        )

    assert resp.status_code == 200
    assert resp.json() == {"created": True}


@pytest.mark.asyncio
async def test_csrf_fails_with_mismatched_token():
    """POST with mismatched cookie vs header → 403."""
    app = _create_test_app()
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/data",
            headers={"X-CSRF-Token": "header-value"},
            cookies={"csrf_token": "different-cookie-value"},
        )

    assert resp.status_code == 403
    body = resp.json()
    assert body["status"] == 403


@pytest.mark.asyncio
async def test_csrf_bypassed_for_bearer_token():
    """POST with Authorization: Bearer ... skips CSRF even without tokens."""
    app = _create_test_app()
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/data",
            headers={"Authorization": "Bearer some-jwt-token"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"created": True}


@pytest.mark.asyncio
async def test_csrf_bypassed_for_exempt_login_path():
    """POST to /api/v1/auth/login without CSRF → success (exempt)."""
    app = _create_test_app()
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/login")

    assert resp.status_code == 200
    assert resp.json() == {"token": "abc"}


@pytest.mark.asyncio
async def test_csrf_bypassed_for_exempt_refresh_path():
    """POST to /api/v1/auth/refresh without CSRF → success (exempt)."""
    app = _create_test_app()
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.post("/api/v1/auth/refresh")

    assert resp.status_code == 200
    assert resp.json() == {"token": "refreshed"}


@pytest.mark.asyncio
async def test_get_requests_skip_csrf():
    """GET to a non-exempt path without CSRF → 200 (only mutations checked)."""
    app = _create_test_app()
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.get("/api/v1/data")

    assert resp.status_code == 200
    assert resp.json() == {"data": "test"}


@pytest.mark.asyncio
async def test_csrf_blocks_put_without_token():
    """PUT without CSRF token → 403."""
    app = _create_test_app()
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.put("/api/v1/data")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_csrf_blocks_delete_without_token():
    """DELETE without CSRF token → 403."""
    app = _create_test_app()
    async with AsyncClient(transport=_transport(app), base_url="http://test") as client:
        resp = await client.delete("/api/v1/data")

    assert resp.status_code == 403


# ── _is_csrf_exempt function tests ───────────────────────────────────


def _make_request(path: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "query_string": b"",
        "root_path": "",
        "headers": raw_headers,
    }
    return Request(scope)


@pytest.mark.parametrize(
    "path, headers, expected",
    [
        # Bearer token → exempt
        ("/api/v1/data", {"Authorization": "Bearer tok"}, True),
        # Exempt paths
        ("/api/v1/auth/login", {}, True),
        ("/api/v1/auth/refresh", {}, True),
        ("/health", {}, True),
        ("/docs", {}, True),
        ("/openapi.json", {}, True),
        ("/redoc", {}, True),
        # Non-exempt
        ("/api/v1/data", {}, False),
        ("/api/v1/users", {}, False),
        # Bearer without "Bearer " prefix → not exempt via token
        ("/api/v1/data", {"Authorization": "Basic abc"}, False),
    ],
    ids=[
        "bearer-token",
        "login-path",
        "refresh-path",
        "health-path",
        "docs-path",
        "openapi-path",
        "redoc-path",
        "non-exempt-data",
        "non-exempt-users",
        "basic-auth-not-exempt",
    ],
)
def test_is_csrf_exempt(path: str, headers: dict[str, str], expected: bool):
    """Parameterized tests for _is_csrf_exempt helper."""
    request = _make_request(path, headers)
    assert _is_csrf_exempt(request) is expected
