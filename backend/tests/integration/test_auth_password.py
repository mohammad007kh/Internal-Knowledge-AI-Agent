"""Integration tests for password-reset and change-password endpoints.

Spec coverage: FR-023, FR-034
  FR-023 - users reset password via time-limited reset link
  FR-034 - passwords meet complexity policy (length, uppercase, digit, special char)
"""
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from src.models.user import Invitation, User
from tests.conftest import get_access_token


@pytest.mark.asyncio
class TestPasswordReset:
    async def test_reset_request_always_202(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/password-reset",
            json={"email": "nobody@example.com"},
        )
        assert resp.status_code == 202

    async def test_reset_request_known_email_also_202(
        self, client: AsyncClient, regular_user: User
    ):
        resp = await client.post(
            "/api/v1/auth/password-reset",
            json={"email": "user@example.com"},
        )
        assert resp.status_code == 202

    async def test_change_password_success(
        self, client: AsyncClient, regular_user: User
    ):
        token = await get_access_token(client, "user@example.com", "User@12345")
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={"current_password": "User@12345", "new_password": "NewPass@99"},
        )
        assert resp.status_code == 204
        # Verify the new password works
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "NewPass@99"},
        )
        assert login.status_code == 200

    async def test_change_password_wrong_current(
        self, client: AsyncClient, regular_user: User
    ):
        token = await get_access_token(client, "user@example.com", "User@12345")
        resp = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={"current_password": "WrongCurrent", "new_password": "NewPass@99"},
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
class TestInvitationSetup:
    async def test_setup_invalid_token(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/auth/setup",
            json={"token": "bad_token", "full_name": "New User", "password": "Valid@1234"},
        )
        assert resp.status_code == 404

    async def test_setup_weak_password(
        self, client: AsyncClient, db_session, admin_user: User
    ):
        raw = secrets.token_urlsafe(32)
        inv = Invitation(
            email="newuser@example.com",
            token=raw,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        db_session.add(inv)
        await db_session.flush()
        resp = await client.post(
            "/api/v1/auth/setup",
            json={"token": raw, "full_name": "New User", "password": "weak"},
        )
        assert resp.status_code == 422
