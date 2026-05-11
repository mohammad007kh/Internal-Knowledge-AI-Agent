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


# ---------------------------------------------------------------------------
# GET /sources/{source_id}/schema-document — admin/owner DB schema viewer (U7)
# ---------------------------------------------------------------------------


class TestSchemaDocumentEndpoint:
    """Unit tests for ``GET /sources/{source_id}/schema-document``.

    Verifies admin/owner read access, 404 fall-through for unknown source,
    404 when no completed study exists, and that a tampered persisted
    document is rejected by the strict :class:`SchemaDocument` validator
    (mapped to a sanitised 500). Plus auth checks for the
    ``reveal-samples`` audit-emit endpoint.
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
        return uuid.UUID("00000000-0000-0000-0000-0000000000a7")

    @pytest.fixture()
    def study_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-000000000077")

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
    def schema_document_dict(self) -> dict:
        """A minimal but valid SchemaDocument JSON dict.

        Mirrors the shape :class:`SchemaDocument.model_validate` accepts —
        keeps the test independent of any future drift in optional fields.
        """
        return {
            "dialect": "postgresql",
            "fingerprint": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
            "generated_at": "2026-05-09T12:00:00+00:00",
            "agent_version": "0.4.2",
            "study_duration_ms": 14_300,
            "partial": False,
            "phase_errors": [],
            "tables": [
                {
                    "name": "public.orders",
                    "kind": "table",
                    "row_count_estimate": 410_000,
                    "primary_key": ["id"],
                    "indexes": [
                        {"name": "orders_pkey", "columns": ["id"], "unique": True}
                    ],
                    "columns": [
                        {
                            "name": "id",
                            "type": "uuid",
                            "native_type": "uuid",
                            "nullable": False,
                            "default": None,
                            "sample_values": [],
                            "is_pii_candidate": False,
                            "inferred": False,
                        }
                    ],
                    "relationships": [],
                    "description": "Customer orders.",
                    "tags": ["transactional"],
                }
            ],
            "summary": "Two-table demo",
            "vector_index_ref": None,
        }

    @pytest.fixture()
    def study_row(
        self, study_id: uuid.UUID, schema_document_dict: dict
    ):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        s = MagicMock()
        s.id = study_id
        s.state = "READY"
        s.started_at = datetime(2026, 5, 9, 12, 0, tzinfo=timezone.utc)
        s.finished_at = datetime(2026, 5, 9, 12, 0, 14, tzinfo=timezone.utc)
        s.fingerprint = schema_document_dict["fingerprint"]
        s.schema_document_json = schema_document_dict
        return s

    @pytest.fixture()
    def app(
        self,
        monkeypatch: pytest.MonkeyPatch,
        admin_user,
        db,
        source_row,
        study_row,
    ):
        """FastAPI app with deps overridden for the schema-document endpoint."""
        from unittest.mock import AsyncMock

        from fastapi import FastAPI

        from src.api.middleware.error_handler import register_exception_handlers
        from src.api.v1.sources import _get_source_service, router
        from src.core.database import get_db
        from src.core.deps import get_current_user, require_admin
        from src.repositories.source_repository import SourceRepository

        service_stub = AsyncMock()
        service_stub.get_source = AsyncMock(return_value=source_row)

        async def _get_latest(self, _src_id):  # noqa: ANN001
            return study_row

        monkeypatch.setattr(
            SourceRepository,
            "get_latest_completed_study",
            _get_latest,
            raising=True,
        )

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router, prefix="/sources")

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[require_admin] = lambda: admin_user
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

    def test_admin_gets_schema_document(
        self, client, source_id, study_id, schema_document_dict
    ):
        """Admin sees the full envelope plus the strictly-validated document."""
        resp = client.get(f"/sources/{source_id}/schema-document")
        assert resp.status_code == 200
        body = resp.json()
        assert body["study_id"] == str(study_id)
        assert body["state"] == "READY"
        assert body["fingerprint_short"] == schema_document_dict["fingerprint"][:8]
        # Schema document round-trips through the strict validator.
        assert body["schema_document"]["dialect"] == "postgresql"
        assert body["schema_document"]["tables"][0]["name"] == "public.orders"
        assert body["schema_document"]["partial"] is False

    def test_owner_gets_schema_document(
        self, app, client, owner_user, source_id
    ):
        """Source owner has the same read access as an admin."""
        from src.core.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: owner_user

        resp = client.get(f"/sources/{source_id}/schema-document")
        assert resp.status_code == 200

    # ---------------------------------------------------------------- #
    # Auth + 404 cases
    # ---------------------------------------------------------------- #

    def test_non_owner_non_admin_403(
        self, app, client, stranger_user, source_id
    ):
        """A user who is neither admin nor owner gets 403."""
        from src.core.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: stranger_user

        resp = client.get(f"/sources/{source_id}/schema-document")
        assert resp.status_code == 403

    def test_no_completed_study_returns_404(
        self, app, client, source_id, monkeypatch
    ):
        """When no SchemaStudy has finished, the endpoint returns 404."""
        from src.repositories.source_repository import SourceRepository

        async def _none(self, _src_id):  # noqa: ANN001
            return None

        monkeypatch.setattr(
            SourceRepository,
            "get_latest_completed_study",
            _none,
            raising=True,
        )

        resp = client.get(f"/sources/{source_id}/schema-document")
        assert resp.status_code == 404

    def test_unknown_source_returns_404(self, app, client, source_id):
        """Unknown source id surfaces as 404 (raised by SourceService)."""
        from unittest.mock import AsyncMock

        from src.api.v1.sources import _get_source_service
        from src.core.exceptions import NotFoundError

        service_stub = AsyncMock()
        service_stub.get_source = AsyncMock(
            side_effect=NotFoundError(f"Source {source_id} not found.")
        )
        app.dependency_overrides[_get_source_service] = lambda: service_stub

        resp = client.get(f"/sources/{source_id}/schema-document")
        assert resp.status_code == 404

    def test_tampered_document_returns_500(
        self, app, client, source_id, study_row, monkeypatch
    ):
        """Tampered ``schema_document_json`` fails strict validation → 500.

        We mutate the persisted JSON to inject an unknown top-level key,
        which the strict ``extra='forbid'`` model rejects. The endpoint
        must NOT echo the raw ValidationError text.
        """
        from src.repositories.source_repository import SourceRepository

        broken = dict(study_row.schema_document_json)
        broken["unexpected_field"] = "hostile"  # extra=forbid → ValidationError

        async def _broken(self, _src_id):  # noqa: ANN001
            from unittest.mock import MagicMock

            s = MagicMock()
            s.id = study_row.id
            s.state = study_row.state
            s.started_at = study_row.started_at
            s.finished_at = study_row.finished_at
            s.fingerprint = study_row.fingerprint
            s.schema_document_json = broken
            return s

        monkeypatch.setattr(
            SourceRepository,
            "get_latest_completed_study",
            _broken,
            raising=True,
        )

        resp = client.get(f"/sources/{source_id}/schema-document")
        assert resp.status_code == 500
        body = resp.json()
        # Sanitised — does not include raw Pydantic error details.
        haystack = str(body).lower()
        assert "unexpected_field" not in haystack
        assert "validationerror" not in haystack


class TestRevealSamplesEndpoint:
    """Unit tests for ``POST /sources/{id}/schema-document/reveal-samples``.

    Admin-only audit emit. Returns 204 on success, writes one
    ``source.schema.samples_revealed`` audit row, and 403/404 otherwise.
    """

    @pytest.fixture()
    def admin_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-0000000000aa")

    @pytest.fixture()
    def owner_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-0000000000bb")

    @pytest.fixture()
    def source_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-0000000000d7")

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
    def regular_user(self, owner_id: uuid.UUID):
        from unittest.mock import MagicMock

        from src.models.user import User, UserRole

        u = MagicMock(spec=User)
        u.id = owner_id
        u.email = "owner@example.com"
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
    def audit_calls(self):
        return []

    @pytest.fixture()
    def app(
        self,
        monkeypatch: pytest.MonkeyPatch,
        admin_user,
        db,
        source_row,
        audit_calls,
    ):
        from unittest.mock import AsyncMock

        from fastapi import FastAPI

        from src.api.middleware.error_handler import register_exception_handlers
        from src.api.v1.sources import _get_source_service, router
        from src.core.database import get_db
        from src.core.deps import get_current_user, require_admin
        from src.repositories.admin_audit_log_repository import (
            AdminAuditLogRepository,
        )

        service_stub = AsyncMock()
        service_stub.get_source = AsyncMock(return_value=source_row)

        async def _capture_insert(self, **kwargs):  # noqa: ANN001
            audit_calls.append(kwargs)
            from src.models.admin_audit_log import AdminAuditLog

            return AdminAuditLog(
                admin_user_id=kwargs.get("admin_user_id"),
                action=kwargs.get("action"),
                resource_type=kwargs.get("resource_type"),
                resource_id=kwargs.get("resource_id"),
                ip_address=kwargs.get("ip_address"),
                metadata_=kwargs.get("metadata") or {},
            )

        monkeypatch.setattr(
            AdminAuditLogRepository, "insert", _capture_insert, raising=True
        )

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router, prefix="/sources")

        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[require_admin] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[_get_source_service] = lambda: service_stub

        return app

    @pytest.fixture()
    def client(self, app):
        from fastapi.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as tc:
            yield tc

    def test_admin_emits_audit_204(
        self, client, source_id, audit_calls, admin_id
    ):
        resp = client.post(f"/sources/{source_id}/schema-document/reveal-samples")
        assert resp.status_code == 204
        assert len(audit_calls) == 1
        row = audit_calls[0]
        assert row["action"] == "source.schema.samples_revealed"
        assert row["resource_type"] == "source"
        assert row["resource_id"] == source_id
        assert row["admin_user_id"] == admin_id
        # Metadata is empty by spec — we never echo connection strings or
        # any source config here.
        assert row["metadata"] == {}

    def test_non_admin_gets_403(self, app, client, regular_user, source_id):
        from src.core.deps import require_admin

        # Recreate require_admin's actual behaviour for non-admins.
        from fastapi import HTTPException, status as _status

        def _deny():
            raise HTTPException(
                status_code=_status.HTTP_403_FORBIDDEN,
                detail="Admin role required",
            )

        app.dependency_overrides[require_admin] = _deny

        resp = client.post(f"/sources/{source_id}/schema-document/reveal-samples")
        assert resp.status_code == 403

    def test_unknown_source_returns_404(self, app, client, source_id):
        from unittest.mock import AsyncMock

        from src.api.v1.sources import _get_source_service
        from src.core.exceptions import NotFoundError

        service_stub = AsyncMock()
        service_stub.get_source = AsyncMock(
            side_effect=NotFoundError(f"Source {source_id} not found.")
        )
        app.dependency_overrides[_get_source_service] = lambda: service_stub

        resp = client.post(f"/sources/{source_id}/schema-document/reveal-samples")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /sources — DB sources enqueue tasks.study_source.delay (Slice E1)
# ---------------------------------------------------------------------------


class TestCreateSourceEnqueuesStudySource:
    """Slice E1: ``POST /sources`` for ``type=database`` schedules the
    studying-agent so the U7 schema viewer has a SchemaStudy to render.

    Non-database sources MUST NOT enqueue ``study_source`` — only the
    sync_source task fires for them. The enqueue happens AFTER the create
    transaction commits so a failed insert leaves no orphan job in the queue.
    """

    @pytest.fixture()
    def admin_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-0000000000aa")

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
    def db(self):
        from unittest.mock import AsyncMock, MagicMock

        m = MagicMock()
        m.commit = AsyncMock()
        m.execute = AsyncMock()
        m.flush = AsyncMock()
        return m

    def _make_persisted_source(
        self, source_type_value: str, source_id: uuid.UUID, owner_id: uuid.UUID
    ):
        """Build a Source-shaped MagicMock for the route's response_model."""
        from datetime import datetime, timezone
        from unittest.mock import MagicMock

        from src.models.enums import SourceType

        src = MagicMock()
        src.id = source_id
        src.owner_id = owner_id
        src.name = "DB source"
        if source_type_value == "database":
            src.source_type = SourceType.DATABASE
        else:
            src.source_type = SourceType(source_type_value)
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
        return src

    @pytest.fixture()
    def app(self, monkeypatch: pytest.MonkeyPatch, admin_user, admin_id, db):
        from unittest.mock import AsyncMock, MagicMock

        from fastapi import FastAPI

        from src.api.middleware.error_handler import register_exception_handlers
        from src.api.v1.sources import _get_source_service, router
        from src.core.database import get_db
        from src.core.deps import get_current_user, require_admin
        from src.repositories.admin_audit_log_repository import (
            AdminAuditLogRepository,
        )

        # Patch the audit-log insert so we don't need a real DB session.
        monkeypatch.setattr(
            AdminAuditLogRepository,
            "insert",
            AsyncMock(return_value=None),
            raising=True,
        )

        # Patch the celery .delay so it never reaches a broker. Tests
        # introspect this spy directly.
        from src.tasks import study_source as _study_module

        delay_spy = MagicMock()
        monkeypatch.setattr(
            _study_module.study_source, "delay", delay_spy, raising=True
        )

        # The route's existing sync_source ``current_app.send_task`` call is
        # already wrapped in ``try/except Exception: pass`` so a broker
        # outage during the test silently no-ops — no need to patch it. The
        # study_source ``.delay`` call is the only one we assert on.

        service_stub = AsyncMock()

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router, prefix="/sources")
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[require_admin] = lambda: admin_user
        app.dependency_overrides[_get_source_service] = lambda: service_stub
        app.state.service = service_stub
        app.state.delay_spy = delay_spy
        return app

    @pytest.fixture()
    def client(self, app):
        from fastapi.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as tc:
            yield tc

    def test_database_source_enqueues_study_source_delay(
        self, app, client, admin_id
    ):
        """POST /sources for ``type=database`` calls study_source.delay(source_id)."""
        from unittest.mock import AsyncMock

        source_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
        persisted = self._make_persisted_source(
            source_type_value="database", source_id=source_id, owner_id=admin_id
        )
        app.state.service.create_source_v2 = AsyncMock(return_value=persisted)

        resp = client.post(
            "/sources",
            json={
                "name": "Reporting DB",
                "source_type": "database",
                "connection": {
                    "db_type": "postgresql",
                    "host": "h",
                    "port": 5432,
                    "username": "u",
                    "password": "p",
                    "database": "d",
                    "query": "SELECT 1",
                },
                "description": "",
                "sync_mode": "manual",
                "retrieval_mode": "text_to_query",
                "citations_enabled": True,
                "auto_name_and_description": False,
            },
        )
        assert resp.status_code == 201, resp.text

        # study_source.delay called exactly once with the new source's id.
        delay_spy = app.state.delay_spy
        delay_spy.assert_called_once()
        args = delay_spy.call_args.args
        assert args == (str(source_id),)

    def test_non_database_source_does_not_enqueue_study_source(
        self, app, client, admin_id
    ):
        """Non-DB sources skip the studying-agent — only sync_source fires."""
        from unittest.mock import AsyncMock

        source_id = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
        persisted = self._make_persisted_source(
            source_type_value="web_url", source_id=source_id, owner_id=admin_id
        )
        app.state.service.create_source_v2 = AsyncMock(return_value=persisted)

        resp = client.post(
            "/sources",
            json={
                "name": "Web crawl",
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

        delay_spy = app.state.delay_spy
        delay_spy.assert_not_called()


# ---------------------------------------------------------------------------
# GET /sources/{source_id} — detail enrichment (U10): owner_email + schema_summary
# ---------------------------------------------------------------------------


class TestGetSourceDetailEnrichment:
    """Unit tests for ``GET /sources/{source_id}`` U10 fields.

    Asserts the detail response surfaces ``owner_email`` (joined on
    ``Source.owner_id``) and ``schema_summary`` (the latest *completed*
    SchemaStudy's ``schema_document_json["summary"]``), and that
    ``schema_summary`` is ``null`` when no completed study exists.
    """

    @pytest.fixture()
    def admin_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-0000000000aa")

    @pytest.fixture()
    def owner_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-0000000000bb")

    @pytest.fixture()
    def source_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-0000-0000-0000-0000000000d1")

    @pytest.fixture()
    def owner_email(self) -> str:
        return "owner@example.com"

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
    def source_row(self, source_id: uuid.UUID, owner_id: uuid.UUID):
        """A Source-shaped namespace — SimpleNamespace raises AttributeError
        for fields it doesn't define, so Pydantic's ``from_attributes`` falls
        back to the schema defaults for those (e.g. ``study_state``)."""
        from datetime import datetime, timezone
        from types import SimpleNamespace

        from src.models.enums import SourceType

        now = datetime.now(tz=timezone.utc)
        return SimpleNamespace(
            id=source_id,
            owner_id=owner_id,
            name="Reporting DB",
            source_type=SourceType.DATABASE,
            is_active=True,
            deleted_at=None,
            created_at=now,
            updated_at=now,
            description="Sales reporting warehouse.",
            source_mode="live",
            retrieval_mode="text_to_query",
            sync_mode="manual",
            sync_schedule=None,
            last_synced_at=None,
            next_sync_due_at=None,
            status="ready",
            citations_enabled=True,
            embedder_id=None,
            name_status="ai_set",
            description_status="ai_set",
            auto_name_and_description=True,
            schema_status="READY",
            drift_signal_count=0,
            last_studied_at=now,
            connection_status="healthy",
            connection_last_checked_at=now,
            connection_last_error=None,
        )

    @pytest.fixture()
    def db(self):
        from unittest.mock import AsyncMock, MagicMock

        m = MagicMock()
        m.commit = AsyncMock()
        m.execute = AsyncMock()
        return m

    @pytest.fixture()
    def app(
        self,
        monkeypatch: pytest.MonkeyPatch,
        admin_user,
        db,
        source_row,
        source_id,
        owner_email,
    ):
        from unittest.mock import AsyncMock, MagicMock

        from fastapi import FastAPI

        from src.api.middleware.error_handler import register_exception_handlers
        from src.api.v1.sources import _get_source_service, router
        from src.core.database import get_db
        from src.core.deps import get_current_user, require_admin
        from src.repositories.source_repository import SourceRepository

        service_stub = AsyncMock()
        service_stub.get_source = AsyncMock(return_value=source_row)

        async def _owner_email(self, _src_id):  # noqa: ANN001
            return owner_email

        # Default: a completed study with a summary in its persisted JSON.
        study_obj = MagicMock()
        study_obj.schema_document_json = {
            "summary": "Star-schema sales warehouse with 12 fact/dim tables.",
        }

        async def _latest_completed(self, _src_id):  # noqa: ANN001
            return study_obj

        async def _latest_study(_db, _src_id):  # noqa: ANN001
            # The detail endpoint's own _load_latest_schema_study — return
            # None so the study_state projection branch is a no-op for this
            # test (we exercise schema_summary via get_latest_completed_study).
            return None

        monkeypatch.setattr(
            SourceRepository, "get_owner_email", _owner_email, raising=True
        )
        monkeypatch.setattr(
            SourceRepository,
            "get_latest_completed_study",
            _latest_completed,
            raising=True,
        )
        monkeypatch.setattr(
            "src.api.v1.sources._load_latest_schema_study",
            _latest_study,
            raising=True,
        )

        app = FastAPI()
        register_exception_handlers(app)
        app.include_router(router, prefix="/sources")
        app.dependency_overrides[get_current_user] = lambda: admin_user
        app.dependency_overrides[require_admin] = lambda: admin_user
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[_get_source_service] = lambda: service_stub
        app.state.study_obj = study_obj
        return app

    @pytest.fixture()
    def client(self, app):
        from fastapi.testclient import TestClient

        with TestClient(app, raise_server_exceptions=False) as tc:
            yield tc

    def test_detail_includes_owner_email(self, client, source_id, owner_email):
        resp = client.get(f"/sources/{source_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["owner_email"] == owner_email

    def test_detail_includes_schema_summary_from_completed_study(
        self, client, source_id
    ):
        resp = client.get(f"/sources/{source_id}")
        assert resp.status_code == 200, resp.text
        assert (
            resp.json()["schema_summary"]
            == "Star-schema sales warehouse with 12 fact/dim tables."
        )

    def test_schema_summary_none_when_no_completed_study(
        self, app, client, source_id, monkeypatch
    ):
        from src.repositories.source_repository import SourceRepository

        async def _none(self, _src_id):  # noqa: ANN001
            return None

        monkeypatch.setattr(
            SourceRepository, "get_latest_completed_study", _none, raising=True
        )

        resp = client.get(f"/sources/{source_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["schema_summary"] is None

    def test_schema_summary_none_when_json_missing_summary_key(
        self, app, client, source_id
    ):
        # The JSON exists but has no "summary" key → schema_summary stays null.
        app.state.study_obj.schema_document_json = {"tables": []}
        resp = client.get(f"/sources/{source_id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["schema_summary"] is None
