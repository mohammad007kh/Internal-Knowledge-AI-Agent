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
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware.error_handler import register_exception_handlers
from src.api.v1.users import AdminOnly, _get_user_service, router
from src.core.database import get_db
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
        last_login_at=None,
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


def _fake_db_session() -> MagicMock:
    """Return a stub :class:`AsyncSession` for unit tests.

    Audit-log emit calls go through :class:`AdminAuditLogRepository`
    which issues ``session.add`` (sync) + ``session.flush`` (async) and
    ``session.execute`` for repository reads.  We use a :class:`MagicMock`
    so that ``add`` is sync and explicitly mark async methods as
    :class:`AsyncMock` so ``await`` works.

    ``execute`` returns a result whose ``scalar_one_or_none`` returns
    ``None`` — the audit code tolerates a missing prior user (the role
    lookup just records ``"from": None``).
    """
    db = MagicMock()
    db.execute = AsyncMock()
    db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    db.execute.return_value.scalar_one = MagicMock(return_value=0)
    db.execute.return_value.scalars = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture()
def client(mock_user_service: AsyncMock, admin_user: User):
    """TestClient with admin role bypassed.  All endpoints pass role check."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/users")

    app.dependency_overrides[AdminOnly] = lambda: admin_user
    app.dependency_overrides[_get_user_service] = lambda: mock_user_service
    app.dependency_overrides[get_db] = _fake_db_session

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
    app.dependency_overrides[get_db] = _fake_db_session

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


# ===================================================================
# GET /users  (list)
# ===================================================================


def _patch_user_repo(repo: MagicMock):
    """Patch ``src.api.v1.users.UserRepository`` so ``UserRepository(db)`` → *repo*."""
    return patch("src.api.v1.users.UserRepository", return_value=repo)


@pytest.fixture()
def fake_user_repo() -> MagicMock:
    """A stand-in :class:`UserRepository` with async query methods stubbed."""
    repo = MagicMock()
    repo.list_paginated = AsyncMock(return_value=[])
    repo.count_users = AsyncMock(return_value=0)
    repo.set_active = AsyncMock(return_value=None)
    repo.get_by_id = AsyncMock(return_value=None)
    repo.update = AsyncMock(return_value=None)
    return repo


class TestListUsers:
    """GET /users — paginated, includes deactivated users by default."""

    def test_list_users_includes_deactivated_by_default(
        self, client: TestClient, fake_user_repo: MagicMock
    ):
        active = _make_user(email="active@example.com", role=UserRole.user, is_active=True)
        inactive = _make_user(
            email="gone@example.com", role=UserRole.user, is_active=False
        )
        fake_user_repo.list_paginated.return_value = [active, inactive]
        fake_user_repo.count_users.return_value = 2

        with _patch_user_repo(fake_user_repo):
            resp = client.get("/users")

        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["page_size"] == 50
        assert body["total"] == 2
        emails = {u["email"] for u in body["items"]}
        assert emails == {"active@example.com", "gone@example.com"}
        # default status filter is "all"
        fake_user_repo.list_paginated.assert_awaited_once_with(
            status="all", limit=50, offset=0
        )
        fake_user_repo.count_users.assert_awaited_once_with(status="all")

    def test_list_users_status_active_excludes_deactivated(
        self, client: TestClient, fake_user_repo: MagicMock
    ):
        fake_user_repo.list_paginated.return_value = [
            _make_user(email="active@example.com", is_active=True)
        ]
        fake_user_repo.count_users.return_value = 1

        with _patch_user_repo(fake_user_repo):
            resp = client.get("/users?status=active")

        assert resp.status_code == 200
        fake_user_repo.list_paginated.assert_awaited_once_with(
            status="active", limit=50, offset=0
        )
        fake_user_repo.count_users.assert_awaited_once_with(status="active")

    def test_list_users_status_inactive_only_deactivated(
        self, client: TestClient, fake_user_repo: MagicMock
    ):
        fake_user_repo.list_paginated.return_value = [
            _make_user(email="gone@example.com", is_active=False)
        ]
        fake_user_repo.count_users.return_value = 1

        with _patch_user_repo(fake_user_repo):
            resp = client.get("/users?status=inactive")

        assert resp.status_code == 200
        body = resp.json()
        assert all(u["is_active"] is False for u in body["items"])
        fake_user_repo.list_paginated.assert_awaited_once_with(
            status="inactive", limit=50, offset=0
        )

    def test_list_users_pagination_offset(
        self, client: TestClient, fake_user_repo: MagicMock
    ):
        # total is the unfiltered-by-page count; page 2 → offset (2-1)*10 = 10.
        fake_user_repo.list_paginated.return_value = [
            _make_user(email="page2-a@example.com")
        ]
        fake_user_repo.count_users.return_value = 11

        with _patch_user_repo(fake_user_repo):
            resp = client.get("/users?page=2&page_size=10")

        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 2
        assert body["page_size"] == 10
        assert body["total"] == 11
        assert len(body["items"]) == 1
        fake_user_repo.list_paginated.assert_awaited_once_with(
            status="all", limit=10, offset=10
        )

    def test_list_users_invalid_status_returns_422(self, client: TestClient):
        resp = client.get("/users?status=bogus")
        assert resp.status_code == 422

    def test_list_users_empty_result(
        self, client: TestClient, fake_user_repo: MagicMock
    ):
        with _patch_user_repo(fake_user_repo):
            resp = client.get("/users")

        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

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
# PATCH /users/{user_id}  (activate / deactivate toggle)
# ===================================================================


class TestUpdateUser:
    """PATCH /users/{user_id} — admin update of ``full_name`` / ``is_active``.

    Deactivation delegates to :meth:`UserService.deactivate_user` so the
    self-lock-out guard and refresh-token revocation apply; no-op requests
    do no work and emit no audit row.
    """

    def test_reactivate_flips_is_active_and_audits(
        self, client: TestClient, fake_user_repo: MagicMock
    ):
        target_id = uuid4()
        inactive = _make_user(id=target_id, role=UserRole.user, is_active=False)
        reactivated = _make_user(id=target_id, role=UserRole.user, is_active=True)
        # 1st get_by_id → target (inactive); 2nd → refreshed (active).
        fake_user_repo.get_by_id.side_effect = [inactive, reactivated]
        fake_user_repo.set_active.return_value = reactivated

        with (
            _patch_user_repo(fake_user_repo),
            patch("src.api.v1.users.emit_audit", new=AsyncMock()) as emit,
        ):
            resp = client.patch(f"/users/{target_id}", json={"is_active": True})

        assert resp.status_code == 200
        body = resp.json()
        assert body["is_active"] is True
        fake_user_repo.set_active.assert_awaited_once_with(target_id, True)
        emit.assert_awaited_once()
        assert emit.await_args.kwargs["action"] == "user.reactivate"
        assert emit.await_args.kwargs["resource_type"] == "user"
        assert emit.await_args.kwargs["resource_id"] == target_id

    def test_deactivate_via_patch_revokes_tokens_and_audits_once(
        self,
        client: TestClient,
        fake_user_repo: MagicMock,
        mock_user_service: AsyncMock,
    ):
        target_id = uuid4()
        active = _make_user(id=target_id, role=UserRole.user, is_active=True)
        deactivated = _make_user(id=target_id, role=UserRole.user, is_active=False)
        fake_user_repo.get_by_id.side_effect = [active, deactivated]
        mock_user_service.deactivate_user.return_value = None

        with (
            _patch_user_repo(fake_user_repo),
            patch("src.api.v1.users.emit_audit", new=AsyncMock()) as emit,
        ):
            resp = client.patch(f"/users/{target_id}", json={"is_active": False})

        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        # Delegation reaches UserService (which revokes refresh tokens).
        mock_user_service.deactivate_user.assert_awaited_once()
        # ...and the route does NOT call set_active itself for the false case.
        fake_user_repo.set_active.assert_not_called()
        # Exactly one audit row — not double-logged.
        emit.assert_awaited_once()
        assert emit.await_args.kwargs["action"] == "user.deactivate"

    def test_self_deactivate_via_patch_returns_403(
        self,
        client: TestClient,
        fake_user_repo: MagicMock,
        mock_user_service: AsyncMock,
        admin_user: User,
    ):
        # Admin targets their own (active) account → service raises Forbidden.
        fake_user_repo.get_by_id.return_value = _make_user(
            id=admin_user.id, role=UserRole.admin, is_active=True
        )
        mock_user_service.deactivate_user.side_effect = ForbiddenError(
            "Cannot deactivate your own account."
        )

        with (
            _patch_user_repo(fake_user_repo),
            patch("src.api.v1.users.emit_audit", new=AsyncMock()) as emit,
        ):
            resp = client.patch(
                f"/users/{admin_user.id}", json={"is_active": False}
            )

        assert resp.status_code == 403
        emit.assert_not_awaited()
        fake_user_repo.set_active.assert_not_called()

    def test_noop_patch_active_on_active_user(
        self,
        client: TestClient,
        fake_user_repo: MagicMock,
        mock_user_service: AsyncMock,
    ):
        target_id = uuid4()
        fake_user_repo.get_by_id.return_value = _make_user(
            id=target_id, role=UserRole.user, is_active=True
        )

        with (
            _patch_user_repo(fake_user_repo),
            patch("src.api.v1.users.emit_audit", new=AsyncMock()) as emit,
        ):
            resp = client.patch(f"/users/{target_id}", json={"is_active": True})

        assert resp.status_code == 200
        assert resp.json()["is_active"] is True
        emit.assert_not_awaited()
        fake_user_repo.set_active.assert_not_called()
        mock_user_service.deactivate_user.assert_not_awaited()

    def test_noop_patch_inactive_on_inactive_user(
        self,
        client: TestClient,
        fake_user_repo: MagicMock,
        mock_user_service: AsyncMock,
    ):
        target_id = uuid4()
        fake_user_repo.get_by_id.return_value = _make_user(
            id=target_id, role=UserRole.user, is_active=False
        )

        with (
            _patch_user_repo(fake_user_repo),
            patch("src.api.v1.users.emit_audit", new=AsyncMock()) as emit,
        ):
            resp = client.patch(f"/users/{target_id}", json={"is_active": False})

        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        emit.assert_not_awaited()
        fake_user_repo.set_active.assert_not_called()
        mock_user_service.deactivate_user.assert_not_awaited()

    def test_update_full_name_audits(
        self, client: TestClient, fake_user_repo: MagicMock
    ):
        target_id = uuid4()
        before = _make_user(id=target_id, role=UserRole.user, full_name="Old Name")
        after = _make_user(id=target_id, role=UserRole.user, full_name="New Name")
        fake_user_repo.get_by_id.side_effect = [before, after]

        with (
            _patch_user_repo(fake_user_repo),
            patch("src.api.v1.users.emit_audit", new=AsyncMock()) as emit,
        ):
            resp = client.patch(
                f"/users/{target_id}", json={"full_name": "New Name"}
            )

        assert resp.status_code == 200
        assert resp.json()["full_name"] == "New Name"
        fake_user_repo.update.assert_awaited_once_with(target_id, full_name="New Name")
        emit.assert_awaited_once()
        assert emit.await_args.kwargs["action"] == "user.update"

    def test_update_full_name_noop_when_unchanged(
        self, client: TestClient, fake_user_repo: MagicMock
    ):
        target_id = uuid4()
        fake_user_repo.get_by_id.return_value = _make_user(
            id=target_id, role=UserRole.user, full_name="Same Name"
        )

        with (
            _patch_user_repo(fake_user_repo),
            patch("src.api.v1.users.emit_audit", new=AsyncMock()) as emit,
        ):
            resp = client.patch(
                f"/users/{target_id}", json={"full_name": "Same Name"}
            )

        assert resp.status_code == 200
        emit.assert_not_awaited()
        fake_user_repo.update.assert_not_awaited()

    def test_reactivate_unknown_user_returns_404(
        self, client: TestClient, fake_user_repo: MagicMock
    ):
        fake_user_repo.get_by_id.return_value = None

        with _patch_user_repo(fake_user_repo):
            resp = client.patch(f"/users/{uuid4()}", json={"is_active": True})

        assert resp.status_code == 404

    def test_update_user_noop_returns_current(
        self, client: TestClient, fake_user_repo: MagicMock
    ):
        target_id = uuid4()
        fake_user_repo.get_by_id.return_value = _make_user(id=target_id, is_active=True)

        with _patch_user_repo(fake_user_repo):
            resp = client.patch(f"/users/{target_id}", json={})

        assert resp.status_code == 200
        fake_user_repo.set_active.assert_not_called()

    def test_update_user_non_admin_returns_403(self, non_admin_client: TestClient):
        resp = non_admin_client.patch(f"/users/{uuid4()}", json={"is_active": True})

        assert resp.status_code == 403


# ===================================================================
# Router registration
# ===================================================================


class TestRouterRegistration:
    """Verify the users router is included in the v1 API router."""

    def test_users_router_registered_in_v1(self):
        from src.api.v1.router import api_v1_router

        def _iter_paths(router):
            # Old FastAPI flattened included routes (each exposes `.path`);
            # newer FastAPI wraps them as `_IncludedRouter`, which has no
            # `.path`. There the mount prefix (e.g. "/users") lives on
            # `include_context.prefix` and the wrapped APIRouter is exposed
            # via `original_router`.
            for route in getattr(router, "routes", []):
                path = getattr(route, "path", None)
                if path is not None:
                    yield path
                ctx = getattr(route, "include_context", None)
                prefix = getattr(ctx, "prefix", None)
                if prefix:
                    yield prefix
                nested = getattr(route, "original_router", None)
                if nested is not None:
                    yield from _iter_paths(nested)

        assert any("/users" in p for p in _iter_paths(api_v1_router))
