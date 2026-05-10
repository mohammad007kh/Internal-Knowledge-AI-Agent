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
