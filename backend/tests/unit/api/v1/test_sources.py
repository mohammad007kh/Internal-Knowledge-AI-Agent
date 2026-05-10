"""Unit tests for the sources router — Slice A connection-status filtering.

Asserts that ``available_only=true`` excludes sources whose
``connection_status`` is ``failed`` (auto-demoted by repeated sync
failures) while still surfacing ``degraded`` rows.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock

import pytest


os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")


class TestListWithCountsExcludesFailed:
    """Repository-level guarantee: ``available_only`` adds the connection_status filter."""

    @pytest.mark.asyncio
    async def test_available_only_filter_includes_connection_status_clause(
        self,
    ) -> None:
        """Verify the WHERE clause contains the ``connection_status != 'failed'`` filter.

        We don't need a live DB — capturing the rendered SQL is enough to
        assert the filter is wired. This locks the contract for the chat
        picker query.
        """
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.repositories.source_repository import SourceRepository

        # Build a repo against a mock session that captures the SQL it sees.
        captured_sql: list[str] = []

        async def _execute(stmt, *args, **kwargs):  # noqa: ANN001
            captured_sql.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))

            class _Result:
                @staticmethod
                def all() -> list:
                    return []

                @staticmethod
                def scalar_one() -> int:
                    return 0

            return _Result()

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(side_effect=_execute)
        repo = SourceRepository(session=session)

        await repo.list_with_counts(available_only=True)

        # First captured statement is the SELECT with the filter; second
        # is the COUNT.  Both must include the connection_status guard.
        assert captured_sql, "no SQL was executed"
        joined = "\n".join(captured_sql)
        assert "connection_status" in joined
        assert "'failed'" in joined or "failed" in joined

    @pytest.mark.asyncio
    async def test_available_only_false_omits_connection_status_filter(self) -> None:
        """``available_only=False`` (admin view) does NOT filter on connection_status.

        Admins triage failed sources too — the picker hides them, the admin
        list never should.
        """
        from sqlalchemy.ext.asyncio import AsyncSession

        from src.repositories.source_repository import SourceRepository

        captured_sql: list[str] = []

        async def _execute(stmt, *args, **kwargs):  # noqa: ANN001
            captured_sql.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))

            class _Result:
                @staticmethod
                def all() -> list:
                    return []

                @staticmethod
                def scalar_one() -> int:
                    return 0

            return _Result()

        session = AsyncMock(spec=AsyncSession)
        session.execute = AsyncMock(side_effect=_execute)
        repo = SourceRepository(session=session)

        await repo.list_with_counts(available_only=False)

        joined = "\n".join(captured_sql)
        # ``connection_status`` IS in the SELECT projection (it's a column on
        # Source) — the assertion is that it doesn't appear in a WHERE filter
        # when available_only=False. Look for the comparison literal instead.
        assert "connection_status NOT IN" not in joined
        assert "connection_status =" not in joined


class TestSourceListItemSchema:
    """The new connection_status fields surface on the wire DTOs."""

    def test_list_item_exposes_connection_health_fields(self) -> None:
        from src.schemas.source import SourceListItem

        required = {
            "connection_status",
            "connection_last_checked_at",
            "connection_last_error",
        }
        assert required.issubset(set(SourceListItem.model_fields.keys()))

    def test_response_exposes_connection_health_fields(self) -> None:
        from src.schemas.source import SourceResponse

        required = {
            "connection_status",
            "connection_last_checked_at",
            "connection_last_error",
        }
        assert required.issubset(set(SourceResponse.model_fields.keys()))

    def test_default_connection_status_unknown(self) -> None:
        """Pre-existing rows (or fresh ones) default to ``unknown``."""
        from datetime import datetime, timezone

        from src.models.enums import SourceType
        from src.schemas.source import SourceListItem

        item = SourceListItem(
            id=uuid.uuid4(),
            name="x",
            source_type=SourceType.WEB_URL,
            is_active=True,
            created_at=datetime.now(tz=timezone.utc),
        )
        assert item.connection_status == "unknown"
        assert item.connection_last_checked_at is None
        assert item.connection_last_error is None


# ---------------------------------------------------------------------------
# GET /sources/{source_id}/description-history — admin/owner audit trail
# ---------------------------------------------------------------------------


class TestDescriptionHistoryEndpoint:
    """Unit tests for ``GET /sources/{source_id}/description-history``.

    The endpoint returns a paginated, newest-first audit trail of
    description replacements. Admins and source owners can read; everyone
    else gets 403. Unknown source ids get 404. Pagination boundaries
    (``limit``, ``offset``) and the JOIN-driven ``replaced_by_email``
    field are exercised explicitly.
    """

    @pytest.fixture()
    def admin_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-0000000000aa")

    @pytest.fixture()
    def owner_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-0000000000bb")

    @pytest.fixture()
    def stranger_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-0000000000cc")

    @pytest.fixture()
    def source_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-000000000033")

    @pytest.fixture()
    def admin_user(self, admin_id: uuid.UUID):
        from unittest.mock import MagicMock

        from src.models.user import User, UserRole

        u = MagicMock(spec=User)
        u.id = admin_id
        u.email = "admin@example.com"
        u.role = UserRole.admin
        u.is_active = True
        return u

    @pytest.fixture()
    def owner_user(self, owner_id: uuid.UUID):
        from unittest.mock import MagicMock

        from src.models.user import User, UserRole

        u = MagicMock(spec=User)
        u.id = owner_id
        u.email = "owner@example.com"
        u.role = UserRole.user
        u.is_active = True
        return u

    @pytest.fixture()
    def stranger_user(self, stranger_id: uuid.UUID):
        from unittest.mock import MagicMock

        from src.models.user import User, UserRole

        u = MagicMock(spec=User)
        u.id = stranger_id
        u.email = "stranger@example.com"
        u.role = UserRole.user
        u.is_active = True
        return u

    @pytest.fixture()
    def source_row(self, source_id: uuid.UUID, owner_id: uuid.UUID):
        from unittest.mock import MagicMock

        src = MagicMock()
        src.id = source_id
        src.owner_id = owner_id
        return src

    @pytest.fixture()
    def db(self):
        from unittest.mock import AsyncMock, MagicMock

        m = MagicMock()
        m.commit = AsyncMock()
        m.execute = AsyncMock()
        return m

    @pytest.fixture()
    def history_rows(self, owner_id: uuid.UUID) -> list[dict]:
        """Three fixture rows — newest first; the oldest one is AI-replaced."""
        from datetime import datetime, timezone

        return [
            {
                "id": uuid.UUID("00000000-0000-0000-0000-000000000301"),
                "description": "Old description v3",
                "replaced_at": datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
                "replaced_by": owner_id,
                "replaced_by_email": "owner@example.com",
            },
            {
                "id": uuid.UUID("00000000-0000-0000-0000-000000000302"),
                "description": "Old description v2",
                "replaced_at": datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
                "replaced_by": uuid.UUID("00000000-0000-0000-0000-0000000000dd"),
                "replaced_by_email": "alice@example.com",
            },
            {
                "id": uuid.UUID("00000000-0000-0000-0000-000000000303"),
                "description": "Old description v1 (AI-generated replacement)",
                "replaced_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
                "replaced_by": None,
                "replaced_by_email": None,
            },
        ]

    @pytest.fixture()
    def app(
        self,
        monkeypatch: pytest.MonkeyPatch,
        admin_user,
        db,
        source_row,
        history_rows,
    ):
        """Build a FastAPI app with the sources router and overridden deps.

        The endpoint instantiates a fresh :class:`SourceRepository` inside
        the handler (intentionally — the router function is the only place
        that knows the request-scoped session). We patch the two methods
        the endpoint calls onto the class via ``monkeypatch`` so the
        original implementations are restored at fixture teardown — no
        cross-test contamination.
        """
        from unittest.mock import AsyncMock

        from fastapi import FastAPI

        from src.api.middleware.error_handler import register_exception_handlers
        from src.api.v1.sources import _get_source_service, router
        from src.core.database import get_db
        from src.core.deps import get_current_user
        from src.repositories.source_repository import SourceRepository

        service_stub = AsyncMock()
        service_stub.get_source = AsyncMock(return_value=source_row)

        async def _list_history(self, _src_id, *, limit=20, offset=0):  # noqa: ANN001
            window = history_rows[offset : offset + limit]
            return list(window)

        async def _count_history(self, _src_id):  # noqa: ANN001
            return len(history_rows)

        monkeypatch.setattr(
            SourceRepository, "list_description_history", _list_history, raising=True
        )
        monkeypatch.setattr(
            SourceRepository, "count_description_history", _count_history, raising=True
        )

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router, prefix="/sources")

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[_get_source_service] = lambda: service_stub

        return app

    @pytest.fixture()
    def client(self, app):
        from fastapi.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as tc:
            yield tc

    # ---------------------------------------------------------------- #
    # Success cases
    # ---------------------------------------------------------------- #

    def test_admin_gets_paginated_rows(self, client, source_id, history_rows):
        """Admin sees every row, newest-first, with full envelope."""
        resp = client.get(f"/sources/{source_id}/description-history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == len(history_rows)
        assert body["limit"] == 20
        assert body["offset"] == 0
        assert len(body["items"]) == len(history_rows)
        assert body["items"][0]["description"] == "Old description v3"
        # Newest first ordering — relies on the repo's ORDER BY desc
        # (we mocked it to return rows in already-newest-first order).
        assert body["items"][1]["description"] == "Old description v2"
        assert body["items"][2]["description"] == "Old description v1 (AI-generated replacement)"

    def test_owner_gets_paginated_rows(
        self, app, client, owner_user, source_id, history_rows
    ):
        """Source owner has the same read access as an admin."""
        from src.core.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: owner_user

        resp = client.get(f"/sources/{source_id}/description-history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == len(history_rows)
        assert len(body["items"]) == len(history_rows)

    def test_replaced_by_email_null_when_replaced_by_null(
        self, client, source_id
    ):
        """Rows where ``replaced_by`` is NULL surface ``replaced_by_email = null``."""
        resp = client.get(f"/sources/{source_id}/description-history")
        assert resp.status_code == 200
        body = resp.json()
        ai_row = body["items"][2]
        assert ai_row["replaced_by"] is None
        assert ai_row["replaced_by_email"] is None
        # And the human-replaced rows DO carry an email.
        assert body["items"][0]["replaced_by"] is not None
        assert body["items"][0]["replaced_by_email"] == "owner@example.com"

    # ---------------------------------------------------------------- #
    # Pagination boundaries
    # ---------------------------------------------------------------- #

    def test_pagination_limit_offset_window(self, client, source_id, history_rows):
        """Custom ``limit`` and ``offset`` slice the window correctly."""
        resp = client.get(
            f"/sources/{source_id}/description-history",
            params={"limit": 1, "offset": 1},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == len(history_rows)
        assert body["limit"] == 1
        assert body["offset"] == 1
        assert len(body["items"]) == 1
        # Skipped the newest, picked the middle row.
        assert body["items"][0]["description"] == "Old description v2"

    def test_pagination_limit_max_bound_rejected(self, client, source_id):
        """Above-cap ``limit`` (>100) returns 422 — defends the endpoint contract."""
        resp = client.get(
            f"/sources/{source_id}/description-history",
            params={"limit": 101},
        )
        assert resp.status_code == 422

    def test_pagination_offset_negative_rejected(self, client, source_id):
        """Negative ``offset`` returns 422."""
        resp = client.get(
            f"/sources/{source_id}/description-history",
            params={"offset": -1},
        )
        assert resp.status_code == 422

    def test_pagination_offset_past_end_returns_empty(self, client, source_id, history_rows):
        """Offset past the end yields an empty page but the total stays accurate."""
        resp = client.get(
            f"/sources/{source_id}/description-history",
            params={"offset": 999},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == len(history_rows)
        assert body["items"] == []

    # ---------------------------------------------------------------- #
    # Auth + 404 cases
    # ---------------------------------------------------------------- #

    def test_non_owner_non_admin_403(
        self, app, client, stranger_user, source_id
    ):
        """A user who is neither admin nor owner gets 403."""
        from src.core.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: stranger_user

        resp = client.get(f"/sources/{source_id}/description-history")
        assert resp.status_code == 403

    def test_unknown_source_returns_404(self, app, client, source_id):
        """Unknown source id surfaces as 404 (raised by SourceService.get_source)."""
        from unittest.mock import AsyncMock

        from src.api.v1.sources import _get_source_service
        from src.core.exceptions import NotFoundError

        service_stub = AsyncMock()
        service_stub.get_source = AsyncMock(
            side_effect=NotFoundError(f"Source {source_id} not found.")
        )
        app.dependency_overrides[_get_source_service] = lambda: service_stub

        resp = client.get(f"/sources/{source_id}/description-history")
        assert resp.status_code == 404
