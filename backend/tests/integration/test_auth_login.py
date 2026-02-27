"""Integration tests for POST /api/v1/auth/login."""
import pytest
from httpx import AsyncClient
from src.models.user import User


@pytest.mark.asyncio
class TestLogin:
    async def test_login_success(self, client: AsyncClient, admin_user: User):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Admin@1234"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 900
        assert "must_change_password" in body
        assert "refresh_token" in resp.cookies

    async def test_login_wrong_password(self, client: AsyncClient, admin_user: User):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "wrongpass"},
        )
        assert resp.status_code == 401
        body = resp.json()
        assert body["status"] == 401
        assert "type" in body  # RFC 7807 shape

    async def test_login_unknown_email(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "whatever"},
        )
        assert resp.status_code == 401

    async def test_login_inactive_user(
        self,
        client: AsyncClient,
        db_session,
        regular_user: User,
    ):
        regular_user.is_active = False
        await db_session.flush()
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "User@12345"},
        )
        assert resp.status_code == 401
