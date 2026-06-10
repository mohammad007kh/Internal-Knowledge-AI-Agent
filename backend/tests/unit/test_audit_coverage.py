"""Unit tests asserting that audit-log emit calls fire on every
auth/user/source mutation endpoint.

Each test patches :func:`src.services.audit_service.emit_audit` at the
import sites in ``src.api.v1.auth``, ``src.api.v1.users``, and
``src.api.v1.sources``, fires the endpoint via FastAPI ``TestClient``,
then asserts the patched mock was awaited once with the expected
``action`` / ``resource_type`` kwargs.

These are unit-scope tests: the ``db: AsyncSession`` dependency is
overridden with a :class:`MagicMock`, so no real database session is
opened.  Repository/service layers are mocked at their DI seams.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

# Required env vars must be set before importing src modules.
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
from src.api.v1.auth import _get_auth_service
from src.api.v1.auth import router as auth_router
from src.api.v1.sources import _get_source_service
from src.api.v1.sources import router as sources_router
from src.api.v1.users import AdminOnly, _get_user_service
from src.api.v1.users import router as users_router
from src.core.database import get_db
from src.core.deps import get_current_user, require_admin
from src.core.exceptions import UnauthorizedError
from src.models.user import User, UserRole

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_user(**overrides) -> User:
    """Construct a stub User for ``current_user`` overrides."""
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


def _fake_db_session() -> MagicMock:
    """Stub :class:`AsyncSession` whose async ops are AsyncMocks.

    ``execute`` returns a result with ``scalar_one_or_none -> None`` so any
    repository read inside the endpoint is a benign no-op.
    """
    db = MagicMock()
    db.execute = AsyncMock()
    db.execute.return_value.scalar_one_or_none = MagicMock(return_value=None)
    db.execute.return_value.scalar_one = MagicMock(return_value=0)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# Auth router — login_success / login_failure
# ---------------------------------------------------------------------------


@pytest.fixture()
def auth_client():
    """TestClient mounting only the auth router with all DI overrides."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router, prefix="/auth")

    mock_auth = AsyncMock()
    mock_auth.login = AsyncMock()

    app.dependency_overrides[_get_auth_service] = lambda: mock_auth
    app.dependency_overrides[get_db] = _fake_db_session

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc, mock_auth


class TestAuthAuditCoverage:
    """POST /auth/login emits ``login_success`` or ``login_failure``."""

    def test_login_success_emits_audit(self, auth_client):
        tc, mock_auth = auth_client
        mock_auth.login.return_value = ("access-tok", "refresh-tok", False)

        with patch("src.api.v1.auth.emit_audit", new=AsyncMock()) as mocked_emit:
            resp = tc.post(
                "/auth/login",
                json={"email": "admin@example.com", "password": "Secret1!"},
            )

        assert resp.status_code == 200
        mocked_emit.assert_awaited_once()
        kwargs = mocked_emit.call_args.kwargs
        assert kwargs["action"] == "login_success"
        assert kwargs["resource_type"] == "user"

    def test_login_failure_emits_audit(self, auth_client):
        tc, mock_auth = auth_client
        mock_auth.login.side_effect = UnauthorizedError("Invalid credentials")

        with patch("src.api.v1.auth.emit_audit", new=AsyncMock()) as mocked_emit:
            resp = tc.post(
                "/auth/login",
                json={"email": "admin@example.com", "password": "wrong"},
            )

        assert resp.status_code == 401
        mocked_emit.assert_awaited_once()
        kwargs = mocked_emit.call_args.kwargs
        assert kwargs["action"] == "login_failure"
        assert kwargs["resource_type"] == "user"
        assert kwargs["admin_user_id"] is None
        # The login_failure path masks + hashes the caller-supplied email
        # (PII protection — see src/api/v1/auth.py): the raw address is never
        # stored, only ``email_masked`` (prefix-masked) and ``email_hash``.
        meta = kwargs["metadata"]
        assert meta["email_masked"] == "ad***@example.com"
        assert len(meta["email_hash"]) == 64
        assert "admin@example.com" not in meta["email_masked"]


# ---------------------------------------------------------------------------
# Users router — invite / role_change / deactivate
# ---------------------------------------------------------------------------


@pytest.fixture()
def users_client():
    """TestClient mounting only the users router with admin role bypassed."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(users_router, prefix="/users")

    admin = _make_user(role=UserRole.admin)
    mock_user_service = AsyncMock()

    app.dependency_overrides[AdminOnly] = lambda: admin
    app.dependency_overrides[_get_user_service] = lambda: mock_user_service
    app.dependency_overrides[get_db] = _fake_db_session

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc, mock_user_service, admin


class TestUsersAuditCoverage:
    """Each users mutation emits its expected audit row."""

    def test_invite_emits_audit(self, users_client):
        tc, mock_user_service, _admin = users_client
        invitation = MagicMock()
        invitation.id = uuid4()
        mock_user_service.invite.return_value = (invitation, "raw-token")

        with patch("src.api.v1.users.emit_audit", new=AsyncMock()) as mocked_emit:
            resp = tc.post(
                "/users/invitations",
                json={"email": "new@example.com", "role": "user"},
            )

        assert resp.status_code == 201
        mocked_emit.assert_awaited_once()
        kwargs = mocked_emit.call_args.kwargs
        assert kwargs["action"] == "user.invite"
        assert kwargs["resource_type"] == "user"
        assert kwargs["resource_id"] == invitation.id
        assert kwargs["metadata"]["email"] == "new@example.com"
        assert kwargs["metadata"]["role"] == "user"

    def test_role_change_emits_audit(self, users_client):
        tc, mock_user_service, _admin = users_client
        target_id = uuid4()
        updated_user = _make_user(id=target_id, role=UserRole.admin)
        mock_user_service.change_role.return_value = updated_user

        with patch("src.api.v1.users.emit_audit", new=AsyncMock()) as mocked_emit:
            resp = tc.patch(
                f"/users/{target_id}/role",
                json={"role": "admin"},
            )

        assert resp.status_code == 200
        mocked_emit.assert_awaited_once()
        kwargs = mocked_emit.call_args.kwargs
        assert kwargs["action"] == "user.role_change"
        assert kwargs["resource_type"] == "user"
        assert kwargs["resource_id"] == target_id
        assert kwargs["metadata"]["to"] == "admin"

    def test_deactivate_emits_audit(self, users_client):
        tc, mock_user_service, _admin = users_client
        target_id = uuid4()
        mock_user_service.deactivate_user.return_value = None

        with patch("src.api.v1.users.emit_audit", new=AsyncMock()) as mocked_emit:
            resp = tc.delete(f"/users/{target_id}")

        assert resp.status_code == 204
        mocked_emit.assert_awaited_once()
        kwargs = mocked_emit.call_args.kwargs
        assert kwargs["action"] == "user.deactivate"
        assert kwargs["resource_type"] == "user"
        assert kwargs["resource_id"] == target_id


# ---------------------------------------------------------------------------
# Sources router — create / update / delete
# ---------------------------------------------------------------------------


@pytest.fixture()
def sources_client():
    """TestClient mounting only the sources router with admin role bypassed."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(sources_router, prefix="/sources")

    admin = _make_user(role=UserRole.admin)
    mock_source_service = AsyncMock()

    # Both ``require_admin`` and ``get_current_user`` may be hit by these
    # endpoints (create has both: ``dependencies=[Depends(require_admin)]``
    # AND ``current_user: User = Depends(get_current_user)``).
    app.dependency_overrides[require_admin] = lambda: admin
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[_get_source_service] = lambda: mock_source_service
    app.dependency_overrides[get_db] = _fake_db_session

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc, mock_source_service, admin


def _make_source(**overrides) -> MagicMock:
    """Stub Source ORM row satisfying both ``SourcePublicResponse`` (create
    response) and ``SourceResponse`` (update response).

    Every field these schemas read must be a concrete value — an unset
    attribute on a MagicMock is itself a truthy child mock that fails Pydantic
    validation (e.g. ``name_status`` as a string, ``latest_job`` as None).
    """
    src = MagicMock()
    src.id = overrides.get("id", uuid4())
    src.name = overrides.get("name", "Test Source")
    src.source_type = overrides.get("source_type", "web_url")
    src.source_mode = overrides.get("source_mode", "live")
    src.retrieval_mode = overrides.get("retrieval_mode", "vector_only")
    src.description = overrides.get("description", "")
    src.sync_mode = overrides.get("sync_mode", "manual")
    src.sync_schedule = overrides.get("sync_schedule", None)
    src.last_synced_at = overrides.get("last_synced_at", None)
    src.next_sync_due_at = overrides.get("next_sync_due_at", None)
    src.status = overrides.get("status", "active")
    src.citations_enabled = overrides.get("citations_enabled", True)
    src.created_at = overrides.get("created_at", datetime.now(UTC))
    src.updated_at = overrides.get("updated_at", datetime.now(UTC))
    src.owner_id = overrides.get("owner_id", uuid4())
    src.is_active = overrides.get("is_active", True)
    src.deleted_at = overrides.get("deleted_at", None)
    # AI auto-naming bookkeeping (required strings on SourcePublicResponse).
    src.name_status = overrides.get("name_status", "user_set")
    src.description_status = overrides.get("description_status", "user_set")
    src.auto_name_and_description = overrides.get("auto_name_and_description", False)
    # SourceResponse-only fields (update response uses model_validate, which
    # pulls every attribute off the ORM row).
    src.embedder_id = overrides.get("embedder_id", None)
    src.schema_status = overrides.get("schema_status", None)
    src.drift_signal_count = overrides.get("drift_signal_count", 0)
    src.last_studied_at = overrides.get("last_studied_at", None)
    src.study_state = overrides.get("study_state", None)
    src.tables_documented = overrides.get("tables_documented", None)
    src.tables_partial = overrides.get("tables_partial", None)
    src.last_error_phase = overrides.get("last_error_phase", None)
    src.last_error_message = overrides.get("last_error_message", None)
    src.owner_email = overrides.get("owner_email", "admin@example.com")
    src.schema_summary = overrides.get("schema_summary", None)
    src.connection_status = overrides.get("connection_status", "unknown")
    src.connection_last_checked_at = overrides.get("connection_last_checked_at", None)
    src.connection_last_error = overrides.get("connection_last_error", None)
    # FX35b nested response field — None so Pydantic doesn't validate a mock.
    src.latest_job = overrides.get("latest_job", None)
    return src


class TestSourcesAuditCoverage:
    """Each sources mutation emits its expected audit row."""

    def test_create_emits_audit(self, sources_client):
        tc, mock_source_service, admin = sources_client
        created = _make_source(owner_id=admin.id, name="My Web Source")
        mock_source_service.create_source_v2.return_value = created

        body = {
            "name": "My Web Source",
            "source_type": "web_url",
            "connection": {"url": "https://example.com"},
            "sync_mode": "manual",
        }
        with patch("src.api.v1.sources.emit_audit", new=AsyncMock()) as mocked_emit:
            resp = tc.post("/sources", json=body)

        assert resp.status_code == 201, resp.text
        mocked_emit.assert_awaited_once()
        kwargs = mocked_emit.call_args.kwargs
        assert kwargs["action"] == "source.create"
        assert kwargs["resource_type"] == "source"
        assert kwargs["resource_id"] == created.id
        assert kwargs["metadata"]["name"] == "My Web Source"

    def test_update_emits_audit(self, sources_client):
        tc, mock_source_service, admin = sources_client
        existing = _make_source(owner_id=admin.id)
        updated = _make_source(id=existing.id, owner_id=admin.id, name="Renamed")
        mock_source_service.get_source.return_value = existing
        mock_source_service.update_source.return_value = updated

        with patch("src.api.v1.sources.emit_audit", new=AsyncMock()) as mocked_emit:
            resp = tc.patch(
                f"/sources/{existing.id}",
                json={"name": "Renamed"},
            )

        assert resp.status_code == 200, resp.text
        mocked_emit.assert_awaited_once()
        kwargs = mocked_emit.call_args.kwargs
        assert kwargs["action"] == "source.update"
        assert kwargs["resource_type"] == "source"
        assert kwargs["resource_id"] == existing.id
        assert "name" in kwargs["metadata"]["changed_fields"]

    def test_delete_emits_audit(self, sources_client):
        tc, mock_source_service, admin = sources_client
        existing = _make_source(owner_id=admin.id, name="To Delete")
        mock_source_service.get_source.return_value = existing
        mock_source_service.delete_source.return_value = None

        with patch("src.api.v1.sources.emit_audit", new=AsyncMock()) as mocked_emit:
            resp = tc.delete(f"/sources/{existing.id}")

        assert resp.status_code == 204, resp.text
        mocked_emit.assert_awaited_once()
        kwargs = mocked_emit.call_args.kwargs
        assert kwargs["action"] == "source.delete"
        assert kwargs["resource_type"] == "source"
        assert kwargs["resource_id"] == existing.id
        assert kwargs["metadata"]["name"] == "To Delete"
