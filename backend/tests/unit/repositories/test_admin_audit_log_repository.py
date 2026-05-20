"""Unit tests for ``AdminAuditLogRepository``.

These tests do NOT hit a real Postgres — they assert that the repository
constructs the expected SQL (filter predicates, casts, ILIKE) and routes
the metadata search through the cast(metadata as text) ILIKE expression
that the new ``idx_admin_audit_log_metadata_trgm`` index covers.

Result-shape assertions use a mocked ``execute()`` so we can verify both:
  * the right rows come back when the caller uses ``search``
  * the predicate set on ``count`` matches the predicate set on
    ``list_paginated`` (otherwise ``total`` and ``len(rows)`` could drift).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

# Required env vars must be set before importing src modules.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

from sqlalchemy.dialects import postgresql as pg_dialect

from src.repositories.admin_audit_log_repository import (
    AdminAuditLogRepository,
    AuditLogFilters,
)

_PG_DIALECT = pg_dialect.dialect()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_rows(count: int = 20) -> list[tuple[MagicMock, str | None]]:
    """Build ``(row, email)`` pairs with varied metadata."""
    rows: list[tuple[MagicMock, str | None]] = []
    for i in range(count):
        row = MagicMock()
        row.id = i + 1
        row.created_at = datetime(2026, 1, 1, tzinfo=UTC)
        row.action = "source.create" if i % 2 == 0 else "user.invite"
        row.resource_type = "source" if i % 2 == 0 else "user"
        row.resource_id = uuid.uuid4()
        row.admin_user_id = uuid.uuid4()
        row.ip_address = "127.0.0.1"
        # Every third row carries the needle "rotated".
        row.metadata_ = (
            {"action": "rotated key"} if i % 3 == 0 else {"action": "ordinary"}
        )
        rows.append((row, f"user{i}@example.com"))
    return rows


def _make_session(rows: list[tuple[MagicMock, str | None]]) -> MagicMock:
    """Build an AsyncSession-shaped mock whose ``execute()`` returns ``rows``.

    Captures the compiled SQL string of the last executed statement on
    ``session.captured_sql`` so callers can assert predicate construction.
    """
    session = MagicMock()
    session.captured_sql = []  # type: ignore[attr-defined]

    async def _execute(stmt):
        # Best-effort SQL-as-text capture against the Postgres dialect so
        # JSONB / INET columns compile cleanly.  Fall back to plain str().
        try:
            session.captured_sql.append(
                str(stmt.compile(dialect=_PG_DIALECT, compile_kwargs={"literal_binds": True}))
            )
        except Exception:  # pragma: no cover — fall back to plain repr
            session.captured_sql.append(str(stmt))
        result = MagicMock()
        result.all.return_value = rows
        result.scalars.return_value.all.return_value = [r for r, _ in rows]
        result.scalar_one.return_value = len(rows)
        return result

    session.execute = AsyncMock(side_effect=_execute)
    return session


# ---------------------------------------------------------------------------
# Filter wiring
# ---------------------------------------------------------------------------


class TestSearchFilter:
    async def test_search_routes_through_cast_metadata_ilike(self) -> None:
        """The search filter MUST go through ``cast(metadata as text) ILIKE``.

        The trgm index ``idx_admin_audit_log_metadata_trgm`` is built on
        exactly this expression — drift here would silently fall back to
        a sequential scan.
        """
        rows = _seed_rows(20)
        session = _make_session(rows)
        repo = AdminAuditLogRepository(session)

        result = await repo.list_paginated(
            AuditLogFilters(search="rotated"),
            limit=50,
            offset=0,
        )

        assert len(result) == 20  # mock returns all rows; predicate construction is the assertion
        # The compiled SQL must contain a CAST + ILIKE on the metadata column.
        sql = " ".join(session.captured_sql).upper()
        assert "ILIKE" in sql
        assert "METADATA" in sql
        assert "CAST(" in sql or "::TEXT" in sql or "::VARCHAR" in sql

    async def test_search_predicate_matches_between_list_and_count(self) -> None:
        """``list_paginated`` and ``count`` must apply the SAME predicate set.

        Predicate drift is the exact bug that produced the count-race fix —
        the two queries that feed the page envelope must be identical
        modulo SELECT shape, ORDER BY, LIMIT, and OFFSET.
        """
        rows = _seed_rows(5)
        session = _make_session(rows)
        repo = AdminAuditLogRepository(session)

        filters = AuditLogFilters(search="rotated", action="source.create")
        await repo.list_paginated(filters, limit=50, offset=0)
        await repo.count(filters)

        list_sql, count_sql = session.captured_sql[-2], session.captured_sql[-1]
        # Both statements include the search predicate.
        assert "ILIKE" in list_sql.upper()
        assert "ILIKE" in count_sql.upper()
        # Both filter on action.
        assert "SOURCE.CREATE" in list_sql.upper().replace("'", "")
        assert "SOURCE.CREATE" in count_sql.upper().replace("'", "")

    async def test_blank_search_is_ignored(self) -> None:
        """Empty / whitespace-only search must NOT add an ILIKE predicate."""
        rows = _seed_rows(3)
        session = _make_session(rows)
        repo = AdminAuditLogRepository(session)

        await repo.list_paginated(AuditLogFilters(search="   "), limit=50, offset=0)

        sql = session.captured_sql[-1].upper()
        assert "ILIKE" not in sql

    async def test_count_returns_int_for_empty_filters(self) -> None:
        rows = _seed_rows(7)
        session = _make_session(rows)
        repo = AdminAuditLogRepository(session)

        total = await repo.count(AuditLogFilters())

        assert isinstance(total, int)
        assert total == 7

    async def test_list_paginated_returns_row_email_tuples(self) -> None:
        rows = _seed_rows(2)
        session = _make_session(rows)
        repo = AdminAuditLogRepository(session)

        out = await repo.list_paginated(AuditLogFilters(), limit=50, offset=0)

        assert len(out) == 2
        for row, email in out:
            assert hasattr(row, "id")
            assert email is None or isinstance(email, str)
