"""Unit tests for the auth router (src.api.v1.auth).

Every test overrides ``_get_auth_service`` and (where needed)
``require_authenticated`` so that **no** real database, container, or JWT
logic is involved.

The test app mounts the auth router at ``/auth`` — matching the v1 prefix —
and registers the standard exception handlers so that ``AppError`` subclasses
produce the expected RFC 7807 status codes.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# Provide dummy env vars so ``Settings()`` can instantiate during import.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware.error_handler import register_exception_handlers
from src.api.v1.auth import _get_auth_service, router
from src.core.deps import require_authenticated
from src.core.exceptions import (
    BadRequestError,
    UnauthorizedError,
)
from src.models.user import User, UserRole
from src.services.auth_service import AuthService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_user(**overrides) -> User:
    """Create a minimal ``User`` instance for dependency overrides."""
    defaults = dict(
        id=uuid4(),
        email="user@example.com",
        full_name="Test User",
        hashed_password="hashed",
        role=UserRole.user,
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


@pytest.fixture()
def mock_auth_service() -> AsyncMock:
    return AsyncMock(spec=AuthService)


@pytest.fixture()
def current_user() -> User:
    return _make_user()


@pytest.fixture()
def client(mock_auth_service: AsyncMock, current_user: User):
    """TestClient wired to a minimal FastAPI app with dependency overrides."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/auth")

    app.dependency_overrides[_get_auth_service] = lambda: mock_auth_service
    app.dependency_overrides[require_authenticated] = lambda: current_user

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


# ===================================================================
# POST /auth/login
# ===================================================================


class TestLogin:
    """POST /auth/login"""

    def test_login_success(self, client: TestClient, mock_auth_service: AsyncMock):
        mock_auth_service.login.return_value = ("access-tok", "refresh-tok", False)

        resp = client.post("/auth/login", json={"email": "a@b.com", "password": "Secret1!"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] == "access-tok"
        assert body["token_type"] == "bearer"
        assert body["must_change_password"] is False
        assert "expires_in" in body
        mock_auth_service.login.assert_awaited_once_with("a@b.com", "Secret1!")

    def test_login_must_change_password(self, client: TestClient, mock_auth_service: AsyncMock):
        mock_auth_service.login.return_value = ("tok", "ref", True)

        resp = client.post("/auth/login", json={"email": "a@b.com", "password": "P@ssw0rd"})

        assert resp.status_code == 200
        assert resp.json()["must_change_password"] is True

    def test_login_invalid_credentials(self, client: TestClient, mock_auth_service: AsyncMock):
        mock_auth_service.login.side_effect = UnauthorizedError("Invalid credentials")

        resp = client.post("/auth/login", json={"email": "a@b.com", "password": "wrong"})

        assert resp.status_code == 401

    def test_login_validation_error(self, client: TestClient):
        resp = client.post("/auth/login", json={"email": "not-an-email"})

        assert resp.status_code == 422


# ===================================================================
# POST /auth/refresh
# ===================================================================


class TestRefresh:
    """POST /auth/refresh"""

    def test_refresh_success(self, client: TestClient, mock_auth_service: AsyncMock):
        mock_auth_service.refresh.return_value = ("new-access", "new-refresh", False)

        resp = client.post("/auth/refresh", cookies={"refresh_token": "old-tok"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] == "new-access"
        mock_auth_service.refresh.assert_awaited_once_with("old-tok")

    def test_refresh_missing_cookie(self, client: TestClient):
        resp = client.post("/auth/refresh")

        assert resp.status_code == 401

    def test_refresh_invalid_token(self, client: TestClient, mock_auth_service: AsyncMock):
        mock_auth_service.refresh.side_effect = UnauthorizedError("Token expired")

        resp = client.post("/auth/refresh", cookies={"refresh_token": "expired"})

        assert resp.status_code == 401


# ===================================================================
# POST /auth/logout
# ===================================================================


class TestLogout:
    """POST /auth/logout"""

    def test_logout_with_cookie(self, client: TestClient, mock_auth_service: AsyncMock):
        resp = client.post("/auth/logout", cookies={"refresh_token": "tok"})

        assert resp.status_code == 204
        mock_auth_service.logout.assert_awaited_once_with("tok")

    def test_logout_without_cookie(self, client: TestClient, mock_auth_service: AsyncMock):
        resp = client.post("/auth/logout")

        assert resp.status_code == 204
        mock_auth_service.logout.assert_not_awaited()


# ===================================================================
# POST /auth/setup
# ===================================================================


class TestSetup:
    """POST /auth/setup"""

    def test_setup_success(self, client: TestClient, mock_auth_service: AsyncMock):
        mock_auth_service.accept_invitation.return_value = ("access", "refresh", False)

        resp = client.post(
            "/auth/setup",
            json={
                "token": "invite-tok",
                "full_name": "Jane Doe",
                "password": "Str0ng!Pass",
            },
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"] == "access"
        mock_auth_service.accept_invitation.assert_awaited_once_with(
            "invite-tok", "Jane Doe", "Str0ng!Pass"
        )

    def test_setup_bad_token(self, client: TestClient, mock_auth_service: AsyncMock):
        mock_auth_service.accept_invitation.side_effect = BadRequestError("Invalid invitation token")

        resp = client.post(
            "/auth/setup",
            json={"token": "bad", "full_name": "X", "password": "Str0ng!Pass"},
        )

        assert resp.status_code == 400


# ===================================================================
# POST /auth/password-reset
# ===================================================================


class TestPasswordReset:
    """POST /auth/password-reset"""

    def test_password_reset_returns_202(self, client: TestClient, mock_auth_service: AsyncMock):
        mock_auth_service.request_password_reset.return_value = "some-token"

        resp = client.post("/auth/password-reset", json={"email": "a@b.com"})

        assert resp.status_code == 202
        assert "reset link" in resp.json()["message"].lower()
        mock_auth_service.request_password_reset.assert_awaited_once_with("a@b.com")

    def test_password_reset_unknown_email_still_202(
        self, client: TestClient, mock_auth_service: AsyncMock
    ):
        mock_auth_service.request_password_reset.return_value = None

        resp = client.post("/auth/password-reset", json={"email": "nobody@x.com"})

        assert resp.status_code == 202


# ===================================================================
# POST /auth/password-reset/confirm
# ===================================================================


class TestPasswordResetConfirm:
    """POST /auth/password-reset/confirm"""

    def test_confirm_success(self, client: TestClient, mock_auth_service: AsyncMock):
        resp = client.post(
            "/auth/password-reset/confirm",
            json={"token": "reset-tok", "new_password": "NewP@ss1"},
        )

        assert resp.status_code == 204
        mock_auth_service.confirm_password_reset.assert_awaited_once_with(
            "reset-tok", "NewP@ss1"
        )

    def test_confirm_bad_token(self, client: TestClient, mock_auth_service: AsyncMock):
        mock_auth_service.confirm_password_reset.side_effect = BadRequestError("Invalid token")

        resp = client.post(
            "/auth/password-reset/confirm",
            json={"token": "invalid", "new_password": "NewP@ss1"},
        )

        assert resp.status_code == 400


# ===================================================================
# POST /auth/change-password
# ===================================================================


class TestChangePassword:
    """POST /auth/change-password"""

    def test_change_password_success(
        self, client: TestClient, mock_auth_service: AsyncMock, current_user: User
    ):
        resp = client.post(
            "/auth/change-password",
            json={"current_password": "Old1!pass", "new_password": "New1!pass"},
        )

        assert resp.status_code == 204
        mock_auth_service.change_password.assert_awaited_once_with(
            current_user.id, "Old1!pass", "New1!pass"
        )

    def test_change_password_wrong_current(
        self, client: TestClient, mock_auth_service: AsyncMock
    ):
        mock_auth_service.change_password.side_effect = UnauthorizedError(
            "Current password is incorrect"
        )

        resp = client.post(
            "/auth/change-password",
            json={"current_password": "wrong", "new_password": "New1!pass"},
        )

        assert resp.status_code == 401
