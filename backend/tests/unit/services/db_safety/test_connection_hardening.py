"""Unit tests for ``src.services.db_safety.connection_hardening``."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from src.services.db_safety import connection_hardening as ch
from src.services.db_safety.connection_hardening import (
    DEFAULT_STATEMENT_TIMEOUT_MS,
    harden_connection,
    harden_mssql_connection,
    harden_mysql_connection,
    harden_postgres_connection,
    mssql_connect_args,
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


class _RecordingCursor:
    """A DBAPI-cursor stand-in that records every ``execute()`` call.

    ``fail_on`` is a set of statements (exact match) that should raise when
    executed — mimics a managed-MySQL flavour rejecting one knob.
    """

    def __init__(self, sink: list[str], fail_on: set[str] | None = None) -> None:
        self._sink = sink
        self._fail_on = fail_on or set()
        self.closed = False

    def execute(self, statement: str) -> None:
        self._sink.append(statement)
        if statement in self._fail_on:
            raise RuntimeError(f"server rejected: {statement}")

    def close(self) -> None:
        self.closed = True


class _RecordingDBAPIConnection:
    """A DBAPI-connection stand-in handing out :class:`_RecordingCursor`s."""

    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.executed: list[str] = []
        self._fail_on = fail_on or set()
        self.cursors: list[_RecordingCursor] = []

    def cursor(self) -> _RecordingCursor:
        cur = _RecordingCursor(self.executed, self._fail_on)
        self.cursors.append(cur)
        return cur


def _fake_engine_capturing_connect_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, list[Any]]:
    """Return ``(fake_engine, captured)`` where ``captured`` ends up holding
    the ``connect`` event handler the hardening function registers.

    We patch ``connection_hardening.event.listens_for`` so the
    ``@event.listens_for(engine.sync_engine, "connect")`` decorator just
    stashes the wrapped function instead of touching the real event system.
    """
    captured: list[Any] = []

    def _fake_listens_for(_target: object, identifier: str):  # type: ignore[no-untyped-def]
        assert identifier == "connect"

        def _decorator(fn: Any) -> Any:
            captured.append(fn)
            return fn

        return _decorator

    fake_event = MagicMock()
    fake_event.listens_for = _fake_listens_for
    monkeypatch.setattr(ch, "event", fake_event)

    fake_engine = MagicMock(name="AsyncEngine")
    fake_engine.sync_engine = MagicMock(name="sync_engine")
    return fake_engine, captured


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
# harden_mysql_connection
# ---------------------------------------------------------------------------


class TestHardenMySQLConnection:
    def test_connect_handler_issues_read_only_and_timeout_statements(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine, captured = _fake_engine_capturing_connect_handler(monkeypatch)

        harden_mysql_connection(fake_engine, statement_timeout_ms=15_000)
        assert len(captured) == 1, "expected exactly one connect handler"
        handler = captured[0]

        conn = _RecordingDBAPIConnection()
        handler(conn, MagicMock(name="connection_record"))

        joined = "\n".join(conn.executed)
        assert "SET SESSION TRANSACTION READ ONLY" in joined
        # 15_000 ms — milliseconds for MySQL's max_execution_time.
        assert "SET SESSION max_execution_time = 15000" in joined
        # MariaDB equivalent — seconds (15_000ms → 15s).
        assert "SET SESSION max_statement_time = 15" in joined
        assert "SET SESSION innodb_lock_wait_timeout = 15" in joined
        # Every cursor opened was closed.
        assert all(c.closed for c in conn.cursors)

    def test_a_rejected_set_is_swallowed_and_logged(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        fake_engine, captured = _fake_engine_capturing_connect_handler(monkeypatch)
        harden_mysql_connection(fake_engine, statement_timeout_ms=10_000)
        handler = captured[0]

        # Mimic e.g. PlanetScale rejecting max_statement_time.
        fail_on = {"SET SESSION max_statement_time = 10"}
        conn = _RecordingDBAPIConnection(fail_on=fail_on)

        with caplog.at_level(logging.WARNING, logger=ch.logger.name):
            handler(conn, MagicMock())  # must NOT raise

        # All four statements were still attempted (the failure didn't abort).
        joined = "\n".join(conn.executed)
        assert "SET SESSION TRANSACTION READ ONLY" in joined
        assert "SET SESSION max_execution_time = 10000" in joined
        assert "SET SESSION max_statement_time = 10" in joined
        assert "SET SESSION innodb_lock_wait_timeout = 10" in joined
        # And the rejection was logged.
        assert any("server rejected" in r.getMessage() for r in caplog.records)

    def test_rejects_non_positive_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine, _ = _fake_engine_capturing_connect_handler(monkeypatch)
        with pytest.raises(ValueError, match="must be positive"):
            harden_mysql_connection(fake_engine, statement_timeout_ms=0)

    def test_is_idempotent_per_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Calling twice on the same engine must not stack a second connect
        # handler (otherwise every ``SET SESSION ...`` would run twice).
        fake_engine, captured = _fake_engine_capturing_connect_handler(monkeypatch)
        harden_mysql_connection(fake_engine, statement_timeout_ms=15_000)
        harden_mysql_connection(fake_engine, statement_timeout_ms=15_000)
        assert len(captured) == 1


# ---------------------------------------------------------------------------
# harden_mssql_connection
# ---------------------------------------------------------------------------


class TestHardenMSSQLConnection:
    def test_connect_handler_issues_lock_timeout_and_isolation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine, captured = _fake_engine_capturing_connect_handler(monkeypatch)

        harden_mssql_connection(fake_engine, statement_timeout_ms=20_000)
        assert len(captured) == 1
        handler = captured[0]

        conn = _RecordingDBAPIConnection()
        handler(conn, MagicMock())

        joined = "\n".join(conn.executed)
        # LOCK_TIMEOUT is in milliseconds on SQL Server.
        assert "SET LOCK_TIMEOUT 20000" in joined
        assert "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED" in joined
        # No read-only switch — MSSQL has none (documented limitation).
        assert "READ ONLY" not in joined

    def test_a_rejected_set_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine, captured = _fake_engine_capturing_connect_handler(monkeypatch)
        harden_mssql_connection(fake_engine)
        handler = captured[0]

        conn = _RecordingDBAPIConnection(fail_on={"SET LOCK_TIMEOUT 30000"})
        handler(conn, MagicMock())  # must NOT raise
        # Isolation-level statement still attempted.
        assert "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED" in conn.executed

    def test_is_idempotent_per_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_engine, captured = _fake_engine_capturing_connect_handler(monkeypatch)
        harden_mssql_connection(fake_engine)
        harden_mssql_connection(fake_engine)
        assert len(captured) == 1

    def test_mssql_connect_args_carries_command_timeout_in_seconds(self) -> None:
        assert mssql_connect_args(15_000) == {"timeout": 15}
        # Rounds up; minimum 1s.
        assert mssql_connect_args(1) == {"timeout": 1}
        assert mssql_connect_args(2500) == {"timeout": 3}


# ---------------------------------------------------------------------------
# harden_connection dispatcher
# ---------------------------------------------------------------------------


class TestHardenConnectionDispatcher:
    def test_postgresql_is_a_noop_no_handler_registered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine, captured = _fake_engine_capturing_connect_handler(monkeypatch)
        harden_connection(fake_engine, dialect="postgresql")
        assert captured == [], "Postgres must be hardened via the conn string, not events"

    def test_mysql_registers_a_handler(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine, captured = _fake_engine_capturing_connect_handler(monkeypatch)
        harden_connection(fake_engine, dialect="mysql", statement_timeout_ms=9_000)
        assert len(captured) == 1
        conn = _RecordingDBAPIConnection()
        captured[0](conn, MagicMock())
        assert "SET SESSION TRANSACTION READ ONLY" in conn.executed

    def test_mssql_registers_a_handler(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_engine, captured = _fake_engine_capturing_connect_handler(monkeypatch)
        harden_connection(fake_engine, dialect="mssql")
        assert len(captured) == 1
        conn = _RecordingDBAPIConnection()
        captured[0](conn, MagicMock())
        assert any("LOCK_TIMEOUT" in s for s in conn.executed)


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
