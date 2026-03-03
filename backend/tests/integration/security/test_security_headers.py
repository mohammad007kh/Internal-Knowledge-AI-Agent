"""Integration tests for security response headers (T-096).

All tests probe the health endpoint which is unauthenticated and always
returns 200 — we only care about the HTTP response *headers*.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

PROBE_URL = "/api/v1/health"


# ---------------------------------------------------------------------------
# Basic security headers
# ---------------------------------------------------------------------------


async def test_x_content_type_options_header(async_client: AsyncClient) -> None:
    """X-Content-Type-Options must be 'nosniff'."""
    response = await async_client.get(PROBE_URL)
    assert response.headers.get("x-content-type-options") == "nosniff"


async def test_x_frame_options_header(async_client: AsyncClient) -> None:
    """X-Frame-Options must be 'DENY'."""
    response = await async_client.get(PROBE_URL)
    assert response.headers.get("x-frame-options") == "DENY"


async def test_strict_transport_security_header(async_client: AsyncClient) -> None:
    """HSTS must always be present with max-age >= 31536000."""
    response = await async_client.get(PROBE_URL)
    hsts = response.headers.get("strict-transport-security", "")
    assert hsts, "Strict-Transport-Security header missing"
    # Extract max-age value
    for part in hsts.split(";"):
        part = part.strip()
        if part.lower().startswith("max-age="):
            max_age = int(part.split("=", 1)[1])
            assert max_age >= 31536000, f"max-age too short: {max_age}"
            break
    else:
        pytest.fail("max-age directive missing from Strict-Transport-Security")


async def test_content_security_policy_present(async_client: AsyncClient) -> None:
    """Content-Security-Policy header must be present."""
    response = await async_client.get(PROBE_URL)
    assert "content-security-policy" in response.headers


async def test_referrer_policy_header(async_client: AsyncClient) -> None:
    """Referrer-Policy must be present."""
    response = await async_client.get(PROBE_URL)
    assert "referrer-policy" in response.headers


# ---------------------------------------------------------------------------
# Server header suppression
# ---------------------------------------------------------------------------


async def test_no_server_header_or_generic(async_client: AsyncClient) -> None:
    """Server header must not reveal implementation details (uvicorn/python)."""
    response = await async_client.get(PROBE_URL)
    server = response.headers.get("server", "").lower()
    assert server not in {"uvicorn", "python"}, (
        f"Server header leaks implementation: {server!r}"
    )


# ---------------------------------------------------------------------------
# Extended headers (T-096 additions)
# ---------------------------------------------------------------------------


async def test_permissions_policy_header(async_client: AsyncClient) -> None:
    """Permissions-Policy must restrict camera and microphone."""
    response = await async_client.get(PROBE_URL)
    pp = response.headers.get("permissions-policy", "")
    assert "camera" in pp, f"camera directive missing from Permissions-Policy: {pp!r}"
    assert "microphone" in pp, f"microphone directive missing from Permissions-Policy: {pp!r}"


async def test_x_request_id_present_in_response(async_client: AsyncClient) -> None:
    """X-Request-ID must be present in every response."""
    response = await async_client.get(PROBE_URL)
    assert "x-request-id" in response.headers, "X-Request-ID header missing from response"
    # Must be a non-empty string
    assert response.headers["x-request-id"].strip()


# ---------------------------------------------------------------------------
# CORS behaviour
# ---------------------------------------------------------------------------


async def test_cors_rejects_arbitrary_origin(async_client: AsyncClient) -> None:
    """Requests from an unlisted origin must not receive a wildcard ACAO header."""
    response = await async_client.get(
        PROBE_URL,
        headers={"Origin": "https://evil.example.com"},
    )
    acao = response.headers.get("access-control-allow-origin", "")
    assert acao != "*", "CORS must not allow arbitrary origins with '*'"
    assert "evil.example.com" not in acao


async def test_cors_allows_whitelisted_origin(async_client: AsyncClient) -> None:
    """A whitelisted origin must receive the correct ACAO header."""
    # The app's ALLOWED_ORIGINS contains "http://localhost:3000" by default in tests.
    whitelisted = "http://localhost:3000"
    response = await async_client.get(
        PROBE_URL,
        headers={"Origin": whitelisted},
    )
    acao = response.headers.get("access-control-allow-origin", "")
    assert acao == whitelisted, (
        f"Expected ACAO={whitelisted!r}, got {acao!r}"
    )
