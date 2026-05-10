"""Unit tests for the admin audit-log read endpoint.

Covers the route at ``GET /api/v1/admin/audit-log`` end-to-end (FastAPI
``TestClient``) with the database session overridden by a mock.  We assert:

  * happy path — page is shaped per the schema, repo is called once.
  * filter combinations — ``action`` / ``resource_type`` / ``admin_user_id``
    / date range / ``search`` are forwarded into the
    :class:`AuditLogFilters` dataclass without mangling.
  * invalid date range (``from`` > ``to``) returns 422.
  * pagination — page math (``offset = (page - 1) * page_size``) and the
    ``page_size`` cap (max 200, defaults to 50).
  * admin-only — non-admin caller receives 403; missing token receives 401.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
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
from src.api.v1.admin.audit_log import router as audit_log_router
from src.core.database import get_db
from src.core.deps import get_current_user, require_admin
from src.core.exceptions import ForbiddenError, UnauthorizedError
from src.models.user import User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(role: UserRole = UserRole.admin) -> User:
    """Stub User compatible with FastAPI dependency_overrides."""
    user = MagicMock(spec=User)
    user.id = uuid4()
    user.email = "admin@example.com"
    user.full_name = "Admin User"
    user.hashed_password = "hashed"
    user.role = role
    user.is_active = True
    user.must_change_password = False
    user.created_at = datetime.now(UTC)
    user.updated_at = datetime.now(UTC)
    return user


def _make_log_row(**overrides) -> MagicMock:
    """Stub AdminAuditLog row matching the columns the route reads."""
    row = MagicMock()
    row.id = overrides.get("id", 42)
    row.created_at = overrides.get("created_at", datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
    row.action = overrides.get("action", "source.create")
    row.resource_type = overrides.get("resource_type", "source")
    row.resource_id = overrides.get("resource_id", uuid4())
    row.admin_user_id = overrides.get("admin_user_id", uuid4())
    row.ip_address = overrides.get("ip_address", "127.0.0.1")
    row.metadata_ = overrides.get("metadata", {"name": "Acme"})
    return row


def _fake_db_session() -> MagicMock:
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    # `async with db.begin():` — return an async context manager. The route
    # wraps both repo reads in a single transaction (snapshot consistency);
    # the test session needs to honour that protocol without a real engine.
    txn = AsyncMock()
    txn.__aenter__ = AsyncMock(return_value=txn)
    txn.__aexit__ = AsyncMock(return_value=None)
    db.begin = MagicMock(return_value=txn)
    return db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def admin_client(monkeypatch):
    """TestClient with the admin role bypassed and the repo mocked at construction time."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(audit_log_router, prefix="/admin/audit-log")

    admin = _make_user(role=UserRole.admin)
    app.dependency_overrides[require_admin] = lambda: admin
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_db] = _fake_db_session

    # Patch the repository class used inside the route — every test gets a
    # fresh instance, so we keep a handle to the (last) constructed repo on
    # the closure.
    repo = MagicMock()
    repo.list_paginated = AsyncMock(return_value=[])
    repo.count = AsyncMock(return_value=0)

    def _factory(_session):
        return repo

    monkeypatch.setattr(
        "src.api.v1.admin.audit_log.AdminAuditLogRepository", _factory
    )

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc, repo, admin


@pytest.fixture()
def non_admin_client():
    """TestClient where ``require_admin`` raises 403 — emulates a regular user hitting the admin route."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(audit_log_router, prefix="/admin/audit-log")

    def _forbidden() -> User:
        raise ForbiddenError("Requires role: admin")

    app.dependency_overrides[require_admin] = _forbidden
    app.dependency_overrides[get_db] = _fake_db_session

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


@pytest.fixture()
def unauth_client():
    """TestClient where ``require_admin`` raises 401 — emulates an unauthenticated request."""
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(audit_log_router, prefix="/admin/audit-log")

    def _unauth() -> User:
        raise UnauthorizedError("No Bearer token provided")

    app.dependency_overrides[require_admin] = _unauth
    app.dependency_overrides[get_db] = _fake_db_session

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_returns_paginated_envelope(self, admin_client) -> None:
        tc, repo, _admin = admin_client
        row1 = _make_log_row(id=2, action="source.create", resource_type="source")
        row2 = _make_log_row(id=1, action="login_success", resource_type="user")
        repo.list_paginated.return_value = [
            (row1, "alice@example.com"),
            (row2, "bob@example.com"),
        ]
        repo.count.return_value = 2

        resp = tc.get("/admin/audit-log")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 2
        assert body["page"] == 1
        assert body["page_size"] == 50
        assert len(body["items"]) == 2
        first = body["items"][0]
        # IDs are strings (BIGINT-safe wire format).
        assert first["id"] == "2"
        assert first["action"] == "source.create"
        assert first["resource_type"] == "source"
        assert first["admin_user_email"] == "alice@example.com"
        assert first["metadata"] == {"name": "Acme"}
        # user_agent reserved for forward compat.
        assert first["user_agent"] is None

    def test_system_event_row_emits_null_admin_email(self, admin_client) -> None:
        tc, repo, _admin = admin_client
        row = _make_log_row(admin_user_id=None, action="login_failure")
        repo.list_paginated.return_value = [(row, None)]
        repo.count.return_value = 1

        resp = tc.get("/admin/audit-log")

        assert resp.status_code == 200, resp.text
        item = resp.json()["items"][0]
        assert item["admin_user_email"] is None
        assert item["admin_user_id"] is None


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


class TestFilters:
    def test_passes_action_and_resource_type_through(self, admin_client) -> None:
        tc, repo, _admin = admin_client
        repo.list_paginated.return_value = []
        repo.count.return_value = 0

        resp = tc.get(
            "/admin/audit-log",
            params={"action": "source.create", "resource_type": "source"},
        )

        assert resp.status_code == 200
        filters = repo.list_paginated.call_args.args[0]
        assert filters.action == "source.create"
        assert filters.resource_type == "source"
        assert filters.admin_user_id is None
        assert filters.search is None

    def test_passes_admin_user_id_through(self, admin_client) -> None:
        tc, repo, _admin = admin_client
        repo.list_paginated.return_value = []
        repo.count.return_value = 0
        target_id = uuid4()

        resp = tc.get(
            "/admin/audit-log",
            params={"admin_user_id": str(target_id)},
        )

        assert resp.status_code == 200
        filters = repo.list_paginated.call_args.args[0]
        assert filters.admin_user_id == target_id

    def test_passes_date_range_and_search(self, admin_client) -> None:
        tc, repo, _admin = admin_client
        repo.list_paginated.return_value = []
        repo.count.return_value = 0

        resp = tc.get(
            "/admin/audit-log",
            params={
                "from": "2026-01-01T00:00:00Z",
                "to": "2026-02-01T00:00:00Z",
                "search": "rotated",
            },
        )

        assert resp.status_code == 200
        filters = repo.list_paginated.call_args.args[0]
        assert filters.from_ == datetime(2026, 1, 1, tzinfo=UTC)
        assert filters.to == datetime(2026, 2, 1, tzinfo=UTC)
        assert filters.search == "rotated"

    def test_invalid_date_range_returns_422(self, admin_client) -> None:
        tc, repo, _admin = admin_client

        resp = tc.get(
            "/admin/audit-log",
            params={
                "from": "2026-02-01T00:00:00Z",
                "to": "2026-01-01T00:00:00Z",
            },
        )

        assert resp.status_code == 422
        # Repo must NOT have been hit when the request is rejected upfront.
        repo.list_paginated.assert_not_called()
        repo.count.assert_not_called()

    def test_rejects_garbage_uuid_with_422(self, admin_client) -> None:
        tc, repo, _admin = admin_client

        resp = tc.get(
            "/admin/audit-log",
            params={"admin_user_id": "not-a-uuid"},
        )

        assert resp.status_code == 422
        repo.list_paginated.assert_not_called()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    def test_page_2_offsets_correctly(self, admin_client) -> None:
        tc, repo, _admin = admin_client
        repo.list_paginated.return_value = []
        repo.count.return_value = 123

        resp = tc.get("/admin/audit-log", params={"page": 2, "page_size": 25})

        assert resp.status_code == 200
        kwargs = repo.list_paginated.call_args.kwargs
        assert kwargs["limit"] == 25
        assert kwargs["offset"] == 25  # (2-1) * 25
        body = resp.json()
        assert body["page"] == 2
        assert body["page_size"] == 25
        assert body["total"] == 123

    def test_page_size_cap_returns_422(self, admin_client) -> None:
        tc, repo, _admin = admin_client
        repo.list_paginated.return_value = []
        repo.count.return_value = 0

        resp = tc.get("/admin/audit-log", params={"page_size": 9999})

        assert resp.status_code == 422
        repo.list_paginated.assert_not_called()

    def test_page_zero_returns_422(self, admin_client) -> None:
        tc, repo, _admin = admin_client

        resp = tc.get("/admin/audit-log", params={"page": 0})

        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAdminOnly:
    def test_non_admin_returns_403(self, non_admin_client) -> None:
        resp = non_admin_client.get("/admin/audit-log")
        assert resp.status_code == 403

    def test_unauthenticated_returns_401(self, unauth_client) -> None:
        resp = unauth_client.get("/admin/audit-log")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Snapshot consistency (count race regression)
# ---------------------------------------------------------------------------


class TestSnapshotConsistency:
    """Regression: list_paginated() and count() must run in the same txn.

    Without a wrapping transaction, an audit row appended between the two
    awaits would make `total` larger than `len(rows)` warrants — the client
    would render a "next page" button that paginates into a phantom row.
    """

    def test_both_repo_reads_run_inside_db_begin(self, admin_client, monkeypatch) -> None:
        tc, repo, _admin = admin_client

        # Track ordering: did `db.begin().__aenter__` fire before either
        # repo read, and `__aexit__` after both?
        events: list[str] = []

        async def _list(*_args, **_kwargs):
            events.append("list_paginated")
            return [(_make_log_row(id=1), "alice@example.com")]

        async def _count(*_args, **_kwargs):
            events.append("count")
            return 1

        repo.list_paginated.side_effect = _list
        repo.count.side_effect = _count

        # Replace the dependency override with a session whose `begin()`
        # appends to the same `events` list so we can assert ordering.
        from src.core.database import get_db as _get_db

        def _instrumented_session():
            db = MagicMock()
            db.execute = AsyncMock()
            db.flush = AsyncMock()
            db.commit = AsyncMock()
            txn = AsyncMock()

            async def _enter(*_a, **_kw):
                events.append("begin")
                return txn

            async def _exit(*_a, **_kw):
                events.append("commit")
                return None

            txn.__aenter__ = _enter
            txn.__aexit__ = _exit
            db.begin = MagicMock(return_value=txn)
            return db

        # Re-attach onto the existing TestClient's app.
        tc.app.dependency_overrides[_get_db] = _instrumented_session

        resp = tc.get("/admin/audit-log")

        assert resp.status_code == 200, resp.text
        # Both repo reads must occur strictly between begin and commit —
        # otherwise the snapshot guarantee is broken.
        assert events[0] == "begin", events
        assert events[-1] == "commit", events
        assert "list_paginated" in events[1:-1]
        assert "count" in events[1:-1]
        # And `total` matches `len(rows)` from the same snapshot.
        body = resp.json()
        assert body["total"] == len(body["items"]) == 1
