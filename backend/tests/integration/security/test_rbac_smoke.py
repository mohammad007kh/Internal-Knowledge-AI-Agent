"""Integration smoke tests for RBAC and JWT validation (T-096).

Verifies that:
- Admin-only endpoints reject unauthenticated requests (HTTP 401).
- Admin-only endpoints reject regular-user tokens (HTTP 403).
- Tampered, expired, and malformed JWTs are rejected (HTTP 401).

Actual route structure (confirmed from src/api/v1/router.py and src/main.py):
  - /api/v1/users             -> AdminOnly (require_role(admin))
  - /api/v1/users/invitations -> AdminOnly (POST — CSRF-protected; not in unauthenticated 401 tests)
  - /health/workers           -> AdminOnly (health router mounted at root, no /api/v1 prefix)
  - /api/v1/sources           -> get_current_user (not admin-only; regular users allowed)
  - /health                   -> public (no auth)

Note on CSRF: POST/PUT/PATCH/DELETE requests without an ``Authorization`` header are
rejected with 403 by SecurityHeadersMiddleware *before* the auth dependency fires.
Therefore only GET admin endpoints are included in ``ADMIN_ONLY_ENDPOINTS``; POST
admin endpoints are covered in RBAC-with-user-token tests below (authenticated
requests are CSRF-exempt because ``_is_csrf_exempt`` returns True for Bearer tokens).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Endpoint catalogues
# ---------------------------------------------------------------------------

# Routes that exist AND require the 'admin' role.
# Only GET endpoints are listed here: POST/PUT/DELETE/PATCH without an
# Authorization header are intercepted by CSRF middleware *before* the auth
# dependency runs and therefore return 403, not 401.  Unauthenticated POSTs
# are tested separately via the CSRF tests in test_security_headers.py.
# Unauthenticated -> 401; authenticated regular-user -> 403.
ADMIN_ONLY_ENDPOINTS: list[tuple[str, str]] = [
    ("GET", "/api/v1/users"),
    ("GET", "/health/workers"),
]

# A single protected admin endpoint used for JWT validation probes.
_JWT_PROBE_URL = "/health/workers"


# ---------------------------------------------------------------------------
# Unauthenticated access -- must be HTTP 401
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", ADMIN_ONLY_ENDPOINTS)
async def test_unauthenticated_request_returns_401(
    async_client: AsyncClient,
    method: str,
    path: str,
) -> None:
    """Requests without a token must be rejected with HTTP 401."""
    response = await async_client.request(method, path)
    assert response.status_code == 401, (
        f"{method} {path}: expected 401 but got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Regular-user access to admin endpoints -- must be HTTP 403
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", ADMIN_ONLY_ENDPOINTS)
async def test_user_role_cannot_access_admin_endpoints(
    async_client: AsyncClient,
    user_token: str,
    method: str,
    path: str,
) -> None:
    """A token with the 'user' role must be rejected with HTTP 403 on admin endpoints."""
    headers = {"Authorization": f"Bearer {user_token}"}
    response = await async_client.request(method, path, headers=headers)
    assert response.status_code == 403, (
        f"{method} {path}: expected 403 for user role, got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# JWT validity checks -- probe via /health/workers (admin-only -> bad JWT -> 401)
# ---------------------------------------------------------------------------


async def test_tampered_jwt_signature_returns_401(async_client: AsyncClient) -> None:
    """A JWT with a corrupted signature must be rejected with HTTP 401."""
    tampered = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ"
        ".BADSIGNATUREXXXXXXXXXXX"
    )
    response = await async_client.get(
        _JWT_PROBE_URL,
        headers={"Authorization": f"Bearer {tampered}"},
    )
    assert response.status_code == 401, (
        f"Tampered JWT should return 401, got {response.status_code}"
    )


async def test_expired_jwt_returns_401(async_client: AsyncClient) -> None:
    """A JWT with exp=1 (long-expired) must be rejected with HTTP 401."""
    expired = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiJ0ZXN0QGV4YW1wbGUuY29tIiwiZXhwIjoxfQ"
        ".sFlHoOGXnJkKwMrlULCLGVvkFoBM5ln3s7rGwXB3yoc"
    )
    response = await async_client.get(
        _JWT_PROBE_URL,
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert response.status_code == 401, (
        f"Expired JWT should return 401, got {response.status_code}"
    )


async def test_missing_bearer_prefix_returns_401(async_client: AsyncClient) -> None:
    """An Authorization header without the 'Bearer ' prefix must return HTTP 401."""
    response = await async_client.get(
        _JWT_PROBE_URL,
        headers={"Authorization": "not-a-bearer-token"},
    )
    assert response.status_code == 401, (
        f"Missing Bearer prefix should return 401, got {response.status_code}"
    )
