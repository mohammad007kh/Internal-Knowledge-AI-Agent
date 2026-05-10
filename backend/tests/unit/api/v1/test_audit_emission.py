"""Audit-log emission tests for privileged endpoints (Slice B).

Every privileged action MUST land exactly one row in ``admin_audit_log``
with the contracted ``action``, ``resource_type``, and ``resource_id``.
``metadata`` is asserted by KEY only — values may legitimately drift
(timestamps, generated UUIDs, sanitised messages) and locking the test on
exact values would force every refactor to update fixtures.

Coverage matrix
---------------
* ``auth.py`` ``login`` → ``login_success``
* ``auth.py`` ``login`` (UnauthorizedError) → ``login_failure``
* ``users.py`` ``invite_user`` → ``user.invite``
* ``users.py`` ``change_user_role`` → ``user.role_change``
* ``users.py`` ``deactivate_user`` → ``user.deactivate``
* ``sources.py`` ``create_source`` → ``source.create``
* ``sources.py`` ``update_source`` (PATCH) → ``source.update``
* ``sources.py`` ``delete_source`` → ``source.delete``

These tests do NOT exercise the ``/credentials`` endpoint — it has its
own audit coverage in ``test_sources_credentials.py``.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")


_ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
_TARGET_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
_INVITATION_ID = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
_SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000077")


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_admin_user() -> MagicMock:
    """Build a User mock with admin role + a real id/email."""
    from src.models.user import User, UserRole

    u = MagicMock(spec=User)
    u.id = _ADMIN_ID
    u.email = "admin@example.com"
    u.role = UserRole.admin
    u.is_active = True
    u.hashed_password = "$2b$12$x" * 4  # noqa: S105 — only read by re-auth flows we don't trigger here
    return u


@pytest.fixture()
def db_session():
    """A MagicMock-backed AsyncSession that absorbs commit/execute/flush."""
    m = MagicMock()
    m.commit = AsyncMock()
    m.execute = AsyncMock()
    m.flush = AsyncMock()
    m.refresh = AsyncMock()
    m.add = MagicMock()
    return m


@pytest.fixture()
def audit_insert_spy(monkeypatch: pytest.MonkeyPatch):
    """Patch :meth:`AdminAuditLogRepository.insert` and hand back the spy.

    Patched at the class so every instance built inside the route handler
    routes to the same spy — the tests can assert call shape regardless of
    whether the route built the repo with the request session, a service
    session, or anything else.
    """
    from src.repositories.admin_audit_log_repository import AdminAuditLogRepository

    spy = AsyncMock(return_value=None)
    monkeypatch.setattr(AdminAuditLogRepository, "insert", spy, raising=True)
    return spy


# ---------------------------------------------------------------------------
# auth.py — login_success / login_failure
# ---------------------------------------------------------------------------


class TestAuthLoginAuditEmission:
    """``POST /auth/login`` audits both success and failure paths."""

    @pytest.fixture()
    def app(self, monkeypatch: pytest.MonkeyPatch, db_session):
        from fastapi import FastAPI

        from src.api.middleware.error_handler import register_exception_handlers
        from src.api.v1.auth import _get_auth_service, router
        from src.core.database import get_db

        auth_service = AsyncMock()

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router, prefix="/auth")
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[_get_auth_service] = lambda: auth_service
        app.state.auth_service = auth_service
        return app

    @pytest.fixture()
    def client(self, app):
        from fastapi.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as tc:
            yield tc

    def test_login_success_emits_login_success_audit(
        self, app, client, audit_insert_spy, monkeypatch: pytest.MonkeyPatch
    ):
        """Successful login → exactly one audit row, action=login_success."""
        from src.repositories.user_repository import UserRepository

        app.state.auth_service.login = AsyncMock(
            return_value=("access-tok", "refresh-tok", False)
        )

        # The route resolves the user via UserRepository(db).get_by_email after
        # the login succeeds — patch it on the class so we don't need a real DB.
        async def _fake_get_by_email(self, email):  # noqa: ANN001
            user = MagicMock()
            user.id = _TARGET_USER_ID
            return user

        monkeypatch.setattr(
            UserRepository, "get_by_email", _fake_get_by_email, raising=True
        )

        resp = client.post(
            "/auth/login",
            json={"email": "user@example.com", "password": "Pw!23456"},
        )
        assert resp.status_code == 200, resp.text

        audit_insert_spy.assert_awaited_once()
        kwargs = audit_insert_spy.await_args.kwargs
        assert kwargs["action"] == "login_success"
        assert kwargs["resource_type"] == "user"
        assert kwargs["resource_id"] == _TARGET_USER_ID
        assert kwargs["admin_user_id"] == _TARGET_USER_ID
        # metadata for login_success is intentionally empty.
        assert kwargs["metadata"] == {}

    def test_login_failure_emits_login_failure_audit_and_re_raises(
        self, app, client, audit_insert_spy
    ):
        """UnauthorizedError → audit row with action=login_failure, then 401.

        Asserts the PII-safe metadata contract:
        * ``email_masked`` has the prefix-mask shape ("ab***@example.com").
        * ``email_hash`` is 64 hex chars (sha256).
        * The raw email value is NOT present in metadata anywhere.
        """
        import json as _json

        from src.core.exceptions import UnauthorizedError

        app.state.auth_service.login = AsyncMock(
            side_effect=UnauthorizedError("bad password")
        )

        raw_email = "victim@example.com"
        resp = client.post(
            "/auth/login",
            json={"email": raw_email, "password": "wrong"},
        )
        # The exception handler maps UnauthorizedError to 401.
        assert resp.status_code == 401, resp.text

        audit_insert_spy.assert_awaited_once()
        kwargs = audit_insert_spy.await_args.kwargs
        assert kwargs["action"] == "login_failure"
        assert kwargs["resource_type"] == "user"
        assert kwargs["resource_id"] is None
        assert kwargs["admin_user_id"] is None
        meta = kwargs["metadata"]
        assert set(meta.keys()) == {"email_masked", "email_hash", "reason"}

        # (a) masked form keeps first 2 chars of local-part, full domain.
        masked = meta["email_masked"]
        assert masked == "vi***@example.com", masked
        # (b) raw email substring NEVER appears anywhere in metadata.
        serialised = _json.dumps(meta)
        assert raw_email not in serialised
        # (c) sha256 hex is 64 chars + lowercase hex only.
        h = meta["email_hash"]
        assert isinstance(h, str)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# users.py — invite / role_change / deactivate
# ---------------------------------------------------------------------------


class TestUsersAuditEmission:
    """Privileged ``/users`` endpoints all emit one audit row each."""

    @pytest.fixture()
    def app(self, db_session):
        from fastapi import FastAPI

        from src.api.middleware.error_handler import register_exception_handlers
        from src.api.v1.users import _get_user_service, router
        from src.core.database import get_db
        from src.core.deps import get_current_user, require_role

        user_service = AsyncMock()

        admin = _make_admin_user()
        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router, prefix="/users")
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[_get_user_service] = lambda: user_service
        app.dependency_overrides[get_current_user] = lambda: admin
        # ``require_role(UserRole.admin)`` is constructed at module load time,
        # so the dependency function is already a closure — we override the
        # *factory* output by overriding the closure itself. The simplest path
        # is to override the underlying ``get_current_user`` and rely on the
        # role check passing because our admin mock has UserRole.admin.
        from src.api.v1.users import AdminOnly

        app.dependency_overrides[AdminOnly] = lambda: admin
        app.state.user_service = user_service
        app.state.admin = admin
        return app

    @pytest.fixture()
    def client(self, app):
        from fastapi.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as tc:
            yield tc

    def test_invite_emits_user_invite_audit(self, app, client, audit_insert_spy):
        invitation = MagicMock()
        invitation.id = _INVITATION_ID
        app.state.user_service.invite = AsyncMock(
            return_value=(invitation, "raw-token")
        )

        resp = client.post(
            "/users/invitations",
            json={"email": "new@example.com", "role": "user"},
        )
        assert resp.status_code == 201, resp.text

        audit_insert_spy.assert_awaited_once()
        kwargs = audit_insert_spy.await_args.kwargs
        assert kwargs["action"] == "user.invite"
        assert kwargs["resource_type"] == "user"
        assert kwargs["resource_id"] == _INVITATION_ID
        assert kwargs["admin_user_id"] == _ADMIN_ID
        assert set(kwargs["metadata"].keys()) == {"email", "role"}

    def test_role_change_emits_user_role_change_audit(
        self,
        app,
        client,
        audit_insert_spy,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from src.models.user import UserRole
        from src.repositories.user_repository import UserRepository

        target_before = MagicMock()
        target_before.id = _TARGET_USER_ID
        target_before.role = UserRole.user

        async def _fake_get_by_id(self, _id):  # noqa: ANN001
            return target_before

        monkeypatch.setattr(
            UserRepository, "get_by_id", _fake_get_by_id, raising=True
        )

        updated = MagicMock()
        updated.id = _TARGET_USER_ID
        updated.email = "target@example.com"
        updated.full_name = "Target"
        updated.role = UserRole.admin
        updated.is_active = True
        updated.created_at = datetime.now(tz=timezone.utc)
        updated.last_login_at = None

        app.state.user_service.change_role = AsyncMock(return_value=updated)

        resp = client.patch(
            f"/users/{_TARGET_USER_ID}/role",
            json={"role": "admin"},
        )
        assert resp.status_code == 200, resp.text

        audit_insert_spy.assert_awaited_once()
        kwargs = audit_insert_spy.await_args.kwargs
        assert kwargs["action"] == "user.role_change"
        assert kwargs["resource_type"] == "user"
        assert kwargs["resource_id"] == _TARGET_USER_ID
        assert kwargs["admin_user_id"] == _ADMIN_ID
        assert set(kwargs["metadata"].keys()) == {"from", "to"}

    def test_deactivate_emits_user_deactivate_audit(
        self, app, client, audit_insert_spy
    ):
        app.state.user_service.deactivate_user = AsyncMock(return_value=None)

        resp = client.delete(f"/users/{_TARGET_USER_ID}")
        assert resp.status_code == 204, resp.text

        audit_insert_spy.assert_awaited_once()
        kwargs = audit_insert_spy.await_args.kwargs
        assert kwargs["action"] == "user.deactivate"
        assert kwargs["resource_type"] == "user"
        assert kwargs["resource_id"] == _TARGET_USER_ID
        assert kwargs["admin_user_id"] == _ADMIN_ID
        # metadata is empty by spec
        assert kwargs["metadata"] == {}


# ---------------------------------------------------------------------------
# sources.py — create / update / delete
# ---------------------------------------------------------------------------


def _make_source_row(*, source_type_value: str = "web_url") -> MagicMock:
    """Build a Source ORM-shaped MagicMock for response_model validation."""
    from src.models.enums import SourceType

    src = MagicMock()
    src.id = _SOURCE_ID
    src.owner_id = _ADMIN_ID
    src.name = "Demo source"
    # source_type — try to match the StrEnum so the route's branching works.
    if source_type_value == "database":
        src.source_type = SourceType.DATABASE
    else:
        # Use the enum member when present; otherwise the raw string.
        try:
            src.source_type = SourceType(source_type_value)
        except ValueError:
            src.source_type = source_type_value
    src.is_active = True
    src.deleted_at = None
    now = datetime.now(tz=timezone.utc)
    src.created_at = now
    src.updated_at = now
    src.description = None
    src.source_mode = "live"
    src.retrieval_mode = "vector_only"
    src.sync_mode = "manual"
    src.sync_schedule = None
    src.last_synced_at = None
    src.next_sync_due_at = None
    src.status = "ready"
    src.citations_enabled = True
    src.embedder_id = None
    src.name_status = "user_set"
    src.description_status = "user_set"
    src.auto_name_and_description = False
    src.schema_status = None
    src.drift_signal_count = 0
    src.last_studied_at = None
    src.connection_status = "unknown"
    src.connection_last_checked_at = now
    src.connection_last_error = None
    src.study_state = None
    src.tables_documented = None
    src.tables_partial = None
    src.last_error_phase = None
    src.last_error_message = None
    return src


class TestSourcesAuditEmission:
    """``/sources`` mutating endpoints emit audit rows on success."""

    @pytest.fixture()
    def app(self, monkeypatch: pytest.MonkeyPatch, db_session):
        from fastapi import FastAPI

        from src.api.middleware.error_handler import register_exception_handlers
        from src.api.v1.sources import _get_source_service, router
        from src.core.database import get_db
        from src.core.deps import get_current_user, require_admin

        service_stub = AsyncMock()
        admin = _make_admin_user()

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router, prefix="/sources")
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: admin
        app.dependency_overrides[require_admin] = lambda: admin
        app.dependency_overrides[_get_source_service] = lambda: service_stub
        app.state.service = service_stub
        app.state.admin = admin
        return app

    @pytest.fixture()
    def client(self, app):
        from fastapi.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as tc:
            yield tc

    def test_create_emits_source_create_audit(
        self, app, client, audit_insert_spy
    ):
        created = _make_source_row(source_type_value="web_url")
        app.state.service.create_source_v2 = AsyncMock(return_value=created)

        resp = client.post(
            "/sources",
            json={
                "name": "Demo source",
                "source_type": "web_url",
                "connection": {"url": "https://example.com"},
                "description": "",
                "sync_mode": "manual",
                "retrieval_mode": "vector_only",
                "citations_enabled": True,
                "auto_name_and_description": False,
            },
        )
        assert resp.status_code == 201, resp.text

        audit_insert_spy.assert_awaited_once()
        kwargs = audit_insert_spy.await_args.kwargs
        assert kwargs["action"] == "source.create"
        assert kwargs["resource_type"] == "source"
        assert kwargs["resource_id"] == _SOURCE_ID
        assert kwargs["admin_user_id"] == _ADMIN_ID
        assert set(kwargs["metadata"].keys()) == {"name", "type"}

    def test_update_emits_source_update_audit(
        self, app, client, audit_insert_spy
    ):
        existing = _make_source_row(source_type_value="web_url")
        updated = _make_source_row(source_type_value="web_url")
        updated.description = "new desc"
        app.state.service.get_source = AsyncMock(return_value=existing)
        app.state.service.update_source = AsyncMock(return_value=updated)

        resp = client.patch(
            f"/sources/{_SOURCE_ID}",
            json={"description": "new desc"},
        )
        assert resp.status_code == 200, resp.text

        audit_insert_spy.assert_awaited_once()
        kwargs = audit_insert_spy.await_args.kwargs
        assert kwargs["action"] == "source.update"
        assert kwargs["resource_type"] == "source"
        assert kwargs["resource_id"] == _SOURCE_ID
        assert kwargs["admin_user_id"] == _ADMIN_ID
        assert set(kwargs["metadata"].keys()) == {"changed_fields"}

    def test_delete_emits_source_delete_audit(
        self, app, client, audit_insert_spy
    ):
        existing = _make_source_row(source_type_value="web_url")
        app.state.service.get_source = AsyncMock(return_value=existing)
        app.state.service.delete_source = AsyncMock(return_value=None)

        resp = client.delete(f"/sources/{_SOURCE_ID}")
        assert resp.status_code == 204, resp.text

        audit_insert_spy.assert_awaited_once()
        kwargs = audit_insert_spy.await_args.kwargs
        assert kwargs["action"] == "source.delete"
        assert kwargs["resource_type"] == "source"
        assert kwargs["resource_id"] == _SOURCE_ID
        assert kwargs["admin_user_id"] == _ADMIN_ID
        # The route stores the ``name`` for forensics — assert key, not value.
        assert "name" in kwargs["metadata"]
