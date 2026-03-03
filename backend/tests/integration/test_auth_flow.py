from __future__ import annotations

import os

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_INTEGRATION_TESTS") != "1",
    reason="Integration tests require RUN_INTEGRATION_TESTS=1 and a live database",
)


class TestLoginRefreshLogout:
    async def test_full_auth_cycle(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Bootstrap1!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        cookies = resp.cookies
        assert "refresh_token" in cookies
        access_token = data["access_token"]

        refresh_resp = await client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": cookies["refresh_token"]},
        )
        assert refresh_resp.status_code == 200
        new_access = refresh_resp.json()["access_token"]
        assert new_access != access_token

        logout_resp = await client.post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {new_access}"},
        )
        assert logout_resp.status_code == 204

        stale_refresh = await client.post(
            "/api/v1/auth/refresh",
            cookies={"refresh_token": cookies["refresh_token"]},
        )
        assert stale_refresh.status_code == 401

    async def test_wrong_password_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "wrong"},
        )
        assert resp.status_code == 401

    async def test_forced_password_change(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Bootstrap1!"},
        )
        assert resp.json().get("must_change_password") is True


class TestInviteFlow:
    async def test_invite_accept_login(
        self, client: AsyncClient, admin_token: str
    ) -> None:
        resp = await client.post(
            "/api/v1/users/invitations",
            json={"email": "newuser@example.com", "role": "user"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 201
        token = resp.json()["invitation_token"]

        setup = await client.post(
            "/api/v1/auth/setup",
            json={"token": token, "password": "Valid123!"},
        )
        assert setup.status_code == 200

        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "newuser@example.com", "password": "Valid123!"},
        )
        assert login.status_code == 200

    async def test_expired_invitation_returns_410(
        self, client: AsyncClient, admin_token: str
    ) -> None:
        resp = await client.post(
            "/api/v1/auth/setup",
            json={"token": "expired_token_abc123", "password": "Valid123!"},
        )
        assert resp.status_code == 410
