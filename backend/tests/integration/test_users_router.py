"""Integration tests for the users router."""
import pytest
from httpx import AsyncClient
from src.models.user import User
from tests.conftest import get_access_token


@pytest.mark.asyncio
class TestUsersRouter:
    async def test_list_users_admin(self, client: AsyncClient, admin_user: User):
        token = await get_access_token(client, "admin@example.com", "Admin@1234")
        resp = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body

    async def test_list_users_regular_user_forbidden(
        self, client: AsyncClient, regular_user: User
    ):
        token = await get_access_token(client, "user@example.com", "User@12345")
        resp = await client.get(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_list_users_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/v1/users")
        assert resp.status_code == 401

    async def test_invite_user(self, client: AsyncClient, admin_user: User):
        token = await get_access_token(client, "admin@example.com", "Admin@1234")
        resp = await client.post(
            "/api/v1/users/invitations",
            headers={"Authorization": f"Bearer {token}"},
            json={"email": "invitee@example.com", "role": "user"},
        )
        assert resp.status_code == 201

    async def test_change_role(
        self, client: AsyncClient, admin_user: User, regular_user: User
    ):
        token = await get_access_token(client, "admin@example.com", "Admin@1234")
        resp = await client.patch(
            f"/api/v1/users/{regular_user.id}/role",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    async def test_deactivate_user(
        self, client: AsyncClient, admin_user: User, regular_user: User
    ):
        token = await get_access_token(client, "admin@example.com", "Admin@1234")
        resp = await client.delete(
            f"/api/v1/users/{regular_user.id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 204
