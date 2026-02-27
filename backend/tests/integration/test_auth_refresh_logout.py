"""Integration tests for refresh and logout endpoints."""
import pytest
from httpx import AsyncClient
from src.models.user import User
from tests.conftest import get_access_token


@pytest.mark.asyncio
class TestRefreshLogout:
    async def test_refresh_success(self, client: AsyncClient, admin_user: User):
        # Login first to obtain the refresh_token cookie
        await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin@1234"},
        )
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_refresh_no_cookie_returns_401(self, client: AsyncClient):
        resp = await client.post("/api/v1/auth/refresh")
        assert resp.status_code == 401

    async def test_logout_clears_cookie(self, client: AsyncClient, admin_user: User):
        token = await get_access_token(client, "admin@example.com", "Admin@1234")
        resp = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204
        # Either the cookie value is empty or max-age=0 is returned
        cookie_value = resp.cookies.get("refresh_token", "")
        set_cookie_header = (resp.headers.get("set-cookie") or "").lower()
        assert cookie_value == "" or "max-age=0" in set_cookie_header
