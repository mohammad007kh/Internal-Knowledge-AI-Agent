"""Unit tests for the **users** router (``src.api.v1.users``).

Covers all admin-only CRUD operations: list, invite, change-role, deactivate.
"""

from __future__ import annotations

import os

# Environment variables must be set BEFORE importing anything that triggers
# ``Settings()`` instantiation in ``src.core.config``.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault(
    "JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!"
)
os.environ.setdefault(
    "JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!"
)
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware.error_handler import register_exception_handlers
from src.api.v1.users import AdminOnly, _get_user_service, router
from src.core.deps import get_current_user
from src.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from src.models.user import User, UserRole
from src.services.user_service import UserService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**overrides) -> User:
    """Create a mock ``User`` with sensible defaults."""
    defaults = dict(
        id=uuid4(),
        email="admin@example.com",
        full_name="Admin User",
        hashed_password="hashed",
        role=UserRole.admin,
        is_active=True,
        must_change_password=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    user = MagicMock(spec=User)
    for k, v in defaults.items():
        setattr(user, k, v)
    return user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def admin_user() -> User:
    return _make_user(role=UserRole.admin)


@pytest.fixture()
def mock_user_service() -> AsyncMock:
    return AsyncMock(spec=UserService)


@pytest.fixture()
def client(mock_user_service: AsyncMock, admin_user: User):
    """TestClient with admin role bypassed.  All endpoints pass role check."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/users")

    app.dependency_overrides[AdminOnly] = lambda: admin_user
    app.dependency_overrides[_get_user_service] = lambda: mock_user_service

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


@pytest.fixture()
def non_admin_client(mock_user_service: AsyncMock):
    """TestClient where the authenticated user is a regular (non-admin) user.

    ``AdminOnly`` is NOT overridden so the role check fires and produces 403.
    ``get_current_user`` is overridden to return a non-admin user so that the
    HTTP Bearer / DB lookup machinery is skipped.
    """
    regular_user = _make_user(role=UserRole.user, email="user@example.com")

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/users")

    app.dependency_overrides[get_current_user] = lambda: regular_user
    app.dependency_overrides[_get_user_service] = lambda: mock_user_service

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


# ===================================================================
# GET /users  (list)
# ===================================================================


class TestListUsers:
    """GET /users"""

    def test_list_users_success(
        self, client: TestClient, mock_user_service: AsyncMock, admin_user: User
    ):
        user_a = _make_user(email="a@example.com", role=UserRole.user)
        user_b = _make_user(email="b@example.com", role=UserRole.admin)
        mock_user_service.list_users.return_value = ([user_a, user_b], 2)

        resp = client.get("/users?limit=10&offset=0")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["limit"] == 10
        assert body["offset"] == 0
        assert len(body["items"]) == 2
        mock_user_service.list_users.assert_awaited_once()

    def test_list_users_default_pagination(
        self, client: TestClient, mock_user_service: AsyncMock
    ):
        mock_user_service.list_users.return_value = ([], 0)

        resp = client.get("/users")

        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 50
        assert body["offset"] == 0
        assert body["total"] == 0
        assert body["items"] == []

    def test_list_users_empty_result(
        self, client: TestClient, mock_user_service: AsyncMock
    ):
        mock_user_service.list_users.return_value = ([], 0)

        resp = client.get("/users")

        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_list_users_non_admin_returns_403(
        self, non_admin_client: TestClient
    ):
        resp = non_admin_client.get("/users")

        assert resp.status_code == 403


# ===================================================================
# POST /users/invitations  (invite)
# ===================================================================


class TestInviteUser:
    """POST /users/invitations"""

    def test_invite_success(
        self, client: TestClient, mock_user_service: AsyncMock
    ):
        invitation = MagicMock()
        mock_user_service.invite.return_value = (invitation, "raw-token")

        resp = client.post(
            "/users/invitations",
            json={"email": "new@example.com", "role": "user"},
        )

        assert resp.status_code == 201
        assert resp.json() == {"detail": "Invitation sent"}
        mock_user_service.invite.assert_awaited_once()

    def test_invite_with_admin_role(
        self, client: TestClient, mock_user_service: AsyncMock
    ):
        invitation = MagicMock()
        mock_user_service.invite.return_value = (invitation, "raw-token")

        resp = client.post(
            "/users/invitations",
            json={"email": "admin-new@example.com", "role": "admin"},
        )

        assert resp.status_code == 201
        assert resp.json() == {"detail": "Invitation sent"}

    def test_invite_duplicate_email_returns_409(
        self, client: TestClient, mock_user_service: AsyncMock
    ):
        mock_user_service.invite.side_effect = ConflictError(
            "Email already registered"
        )

        resp = client.post(
            "/users/invitations",
            json={"email": "exists@example.com", "role": "user"},
        )

        assert resp.status_code == 409

    def test_invite_reinvite_creates_new_invitation(
        self, client: TestClient, mock_user_service: AsyncMock
    ):
        """Re-inviting an email with a pending invitation revokes the old one
        and creates a new one — the service handles this transparently."""
        invitation = MagicMock()
        mock_user_service.invite.return_value = (invitation, "new-token")

        resp = client.post(
            "/users/invitations",
            json={"email": "pending@example.com", "role": "user"},
        )

        assert resp.status_code == 201
        assert resp.json() == {"detail": "Invitation sent"}

    def test_invite_missing_email_returns_422(self, client: TestClient):
        resp = client.post("/users/invitations", json={"role": "user"})

        assert resp.status_code == 422

    def test_invite_invalid_email_returns_422(self, client: TestClient):
        resp = client.post(
            "/users/invitations",
            json={"email": "not-an-email", "role": "user"},
        )

        assert resp.status_code == 422

    def test_invite_non_admin_returns_403(self, non_admin_client: TestClient):
        resp = non_admin_client.post(
            "/users/invitations",
            json={"email": "new@example.com", "role": "user"},
        )

        assert resp.status_code == 403


# ===================================================================
# PATCH /users/{user_id}/role  (change role)
# ===================================================================


class TestChangeUserRole:
    """PATCH /users/{user_id}/role"""

    def test_change_role_success(
        self, client: TestClient, mock_user_service: AsyncMock
    ):
        target_id = uuid4()
        updated_user = _make_user(id=target_id, role=UserRole.admin)
        mock_user_service.change_role.return_value = updated_user

        resp = client.patch(
            f"/users/{target_id}/role",
            json={"role": "admin"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "admin"
        mock_user_service.change_role.assert_awaited_once()

    def test_change_role_to_user(
        self, client: TestClient, mock_user_service: AsyncMock
    ):
        target_id = uuid4()
        updated_user = _make_user(id=target_id, role=UserRole.user)
        mock_user_service.change_role.return_value = updated_user

        resp = client.patch(
            f"/users/{target_id}/role",
            json={"role": "user"},
        )

        assert resp.status_code == 200
        assert resp.json()["role"] == "user"

    def test_change_role_invalid_role_returns_422(self, client: TestClient):
        target_id = uuid4()

        resp = client.patch(
            f"/users/{target_id}/role",
            json={"role": "superadmin"},
        )

        assert resp.status_code == 422

    def test_change_role_missing_body_returns_422(self, client: TestClient):
        target_id = uuid4()

        resp = client.patch(f"/users/{target_id}/role", json={})

        assert resp.status_code == 422

    def test_change_role_self_returns_403(
        self,
        client: TestClient,
        mock_user_service: AsyncMock,
        admin_user: User,
    ):
        mock_user_service.change_role.side_effect = ForbiddenError(
            "Cannot change your own role."
        )

        resp = client.patch(
            f"/users/{admin_user.id}/role",
            json={"role": "user"},
        )

        assert resp.status_code == 403

    def test_change_role_not_found_returns_404(
        self, client: TestClient, mock_user_service: AsyncMock
    ):
        target_id = uuid4()
        mock_user_service.change_role.side_effect = NotFoundError(
            "User not found."
        )

        resp = client.patch(
            f"/users/{target_id}/role",
            json={"role": "admin"},
        )

        assert resp.status_code == 404

    def test_change_role_non_admin_returns_403(
        self, non_admin_client: TestClient
    ):
        target_id = uuid4()

        resp = non_admin_client.patch(
            f"/users/{target_id}/role",
            json={"role": "admin"},
        )

        assert resp.status_code == 403


# ===================================================================
# DELETE /users/{user_id}  (deactivate)
# ===================================================================


class TestDeactivateUser:
    """DELETE /users/{user_id}"""

    def test_deactivate_success(
        self, client: TestClient, mock_user_service: AsyncMock
    ):
        target_id = uuid4()
        mock_user_service.deactivate_user.return_value = None

        resp = client.delete(f"/users/{target_id}")

        assert resp.status_code == 204
        assert resp.content == b""
        mock_user_service.deactivate_user.assert_awaited_once()

    def test_deactivate_self_returns_403(
        self,
        client: TestClient,
        mock_user_service: AsyncMock,
        admin_user: User,
    ):
        mock_user_service.deactivate_user.side_effect = ForbiddenError(
            "Cannot deactivate your own account."
        )

        resp = client.delete(f"/users/{admin_user.id}")

        assert resp.status_code == 403

    def test_deactivate_not_found_returns_404(
        self, client: TestClient, mock_user_service: AsyncMock
    ):
        target_id = uuid4()
        mock_user_service.deactivate_user.side_effect = NotFoundError(
            "User not found."
        )

        resp = client.delete(f"/users/{target_id}")

        assert resp.status_code == 404

    def test_deactivate_non_admin_returns_403(
        self, non_admin_client: TestClient
    ):
        target_id = uuid4()

        resp = non_admin_client.delete(f"/users/{target_id}")

        assert resp.status_code == 403


# ===================================================================
# Router registration
# ===================================================================


class TestRouterRegistration:
    """Verify the users router is included in the v1 API router."""

    def test_users_router_registered_in_v1(self):
        from src.api.v1.router import api_v1_router

        paths = [route.path for route in api_v1_router.routes]
        assert any("/users" in p for p in paths)
