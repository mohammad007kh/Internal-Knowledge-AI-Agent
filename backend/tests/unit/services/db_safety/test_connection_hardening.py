"""Unit tests for ``src.services.db_safety.connection_hardening``."""
from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from src.services.db_safety.connection_hardening import (
    DEFAULT_STATEMENT_TIMEOUT_MS,
    harden_postgres_connection,
    read_only_session,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _options_value(url: str) -> str:
    """Return the (URL-decoded) ``options=`` query value from a URL."""
    parsed = urlsplit(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    assert "options" in qs, f"options= missing from URL: {url}"
    assert len(qs["options"]) == 1, f"duplicate options= entries in {url}"
    return unquote(qs["options"][0])


# ---------------------------------------------------------------------------
# harden_postgres_connection
# ---------------------------------------------------------------------------


class TestHardenPostgresConnection:
    async def test_adds_both_flags_when_no_options_present(self) -> None:
        url = "postgresql://user:pw@host:5432/db"
        out = await harden_postgres_connection(url)
        opts = _options_value(out)
        assert "-c default_transaction_read_only=on" in opts
        assert f"-c statement_timeout={DEFAULT_STATEMENT_TIMEOUT_MS}" in opts

    async def test_uses_custom_statement_timeout(self) -> None:
        url = "postgresql://user:pw@host/db"
        out = await harden_postgres_connection(url, statement_timeout_ms=12345)
        opts = _options_value(out)
        assert "-c statement_timeout=12345" in opts
        # Default timeout should NOT also appear.
        assert f"-c statement_timeout={DEFAULT_STATEMENT_TIMEOUT_MS}" not in opts

    async def test_merges_into_existing_options_param(self) -> None:
        # Caller already passed -c application_name=... — must be preserved.
        url = (
            "postgresql://user:pw@host/db"
            "?options=-c%20application_name%3Dmyapp"
        )
        out = await harden_postgres_connection(url)
        opts = _options_value(out)
        assert "application_name=myapp" in opts
        assert "-c default_transaction_read_only=on" in opts
        assert f"-c statement_timeout={DEFAULT_STATEMENT_TIMEOUT_MS}" in opts

    async def test_idempotent_when_already_hardened(self) -> None:
        url = "postgresql://user:pw@host/db"
        once = await harden_postgres_connection(url)
        twice = await harden_postgres_connection(once)
        # Second call yields a string with the same options= payload (the
        # full URL encoding may differ in ordering, so compare options).
        assert _options_value(once) == _options_value(twice)

    async def test_idempotent_replaces_outdated_timeout(self) -> None:
        url = "postgresql://user:pw@host/db"
        first = await harden_postgres_connection(url, statement_timeout_ms=1000)
        second = await harden_postgres_connection(first, statement_timeout_ms=5000)
        opts = _options_value(second)
        assert "-c statement_timeout=5000" in opts
        assert "-c statement_timeout=1000" not in opts
        # Read-only flag should appear exactly once.
        assert opts.count("-c default_transaction_read_only=on") == 1

    async def test_handles_postgresql_asyncpg_scheme(self) -> None:
        url = "postgresql+asyncpg://user:pw@host/db"
        out = await harden_postgres_connection(url)
        assert out.startswith("postgresql+asyncpg://")
        opts = _options_value(out)
        assert "-c default_transaction_read_only=on" in opts

    async def test_handles_legacy_postgres_scheme(self) -> None:
        url = "postgres://user:pw@host/db"
        out = await harden_postgres_connection(url)
        assert out.startswith("postgres://")
        opts = _options_value(out)
        assert "-c default_transaction_read_only=on" in opts

    async def test_preserves_other_query_params(self) -> None:
        url = "postgresql://u:p@h/db?sslmode=require&connect_timeout=10"
        out = await harden_postgres_connection(url)
        parsed = urlsplit(out)
        qs = parse_qs(parsed.query, keep_blank_values=True)
        assert qs["sslmode"] == ["require"]
        assert qs["connect_timeout"] == ["10"]
        assert "options" in qs

    async def test_rejects_non_postgres_url(self) -> None:
        with pytest.raises(ValueError, match="only supports PostgreSQL"):
            await harden_postgres_connection("mysql://u:p@h/db")

    async def test_rejects_mssql_url(self) -> None:
        with pytest.raises(ValueError, match="only supports PostgreSQL"):
            await harden_postgres_connection("mssql+aioodbc://u:p@h/db")

    async def test_rejects_non_positive_timeout(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            await harden_postgres_connection(
                "postgresql://u:p@h/db", statement_timeout_ms=0
            )
        with pytest.raises(ValueError, match="must be positive"):
            await harden_postgres_connection(
                "postgresql://u:p@h/db", statement_timeout_ms=-1
            )


# ---------------------------------------------------------------------------
# read_only_session
# ---------------------------------------------------------------------------


class TestReadOnlySession:
    """Mock-based tests — testcontainers is intentionally not added as a dep."""

    async def test_issues_set_local_and_rolls_back_on_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Build a mock AsyncSession that records every call.
        executed_sql: list[str] = []
        rollback_called = AsyncMock()
        close_called = AsyncMock()

        async def _fake_execute(stmt, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            # SQLAlchemy `text()` clauses stringify to their SQL body.
            executed_sql.append(str(stmt))
            return MagicMock()

        # session.begin() is itself an async context manager.  We mimic it.
        @asynccontextmanager
        async def _fake_begin():  # type: ignore[no-untyped-def]
            yield

        fake_session = MagicMock()
        fake_session.execute = _fake_execute
        fake_session.begin = _fake_begin
        fake_session.rollback = rollback_called
        fake_session.close = close_called

        # Patch the AsyncSession constructor used inside read_only_session.
        from sqlalchemy.ext import asyncio as sa_async  # noqa: PLC0415

        monkeypatch.setattr(
            sa_async,
            "AsyncSession",
            MagicMock(return_value=fake_session),
        )

        fake_engine = MagicMock(name="AsyncEngine")
        async with read_only_session(fake_engine, statement_timeout_ms=7777) as sess:
            assert sess is fake_session

        # Both SET LOCAL statements were issued.
        assert any(
            "SET LOCAL transaction_read_only TO on" in sql
            for sql in executed_sql
        ), executed_sql
        assert any(
            "SET LOCAL statement_timeout = 7777" in sql for sql in executed_sql
        ), executed_sql

        # Defense-in-depth: explicit ROLLBACK on success path.
        rollback_called.assert_awaited_once()
        # Session is closed on exit.
        close_called.assert_awaited_once()

    async def test_rolls_back_on_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rollback_called = AsyncMock()
        close_called = AsyncMock()

        async def _fake_execute(stmt, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return MagicMock()

        @asynccontextmanager
        async def _fake_begin():  # type: ignore[no-untyped-def]
            yield

        fake_session = MagicMock()
        fake_session.execute = _fake_execute
        fake_session.begin = _fake_begin
        fake_session.rollback = rollback_called
        fake_session.close = close_called

        from sqlalchemy.ext import asyncio as sa_async  # noqa: PLC0415

        monkeypatch.setattr(
            sa_async,
            "AsyncSession",
            MagicMock(return_value=fake_session),
        )

        fake_engine = MagicMock(name="AsyncEngine")

        class _Boom(RuntimeError):
            pass

        with pytest.raises(_Boom):
            async with read_only_session(fake_engine):
                raise _Boom("user code error")

        rollback_called.assert_awaited_once()
        close_called.assert_awaited_once()

    async def test_rejects_non_positive_timeout(self) -> None:
        fake_engine = MagicMock(name="AsyncEngine")
        with pytest.raises(ValueError, match="must be positive"):
            async with read_only_session(fake_engine, statement_timeout_ms=0):
                pass  # pragma: no cover
