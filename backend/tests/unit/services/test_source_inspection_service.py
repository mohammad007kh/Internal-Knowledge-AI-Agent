"""Unit tests for :class:`SourceInspectionService`.

Focus: ``inspect_source`` for the consolidated ``database`` source type.

The "Add database" wizard POSTs ``connection`` in the *structured* shape
(``{db_type, host, port, database, username, password, ssl_mode, ...}`` — the
same shape :class:`DatabaseConnectionConfig` accepts), but
:func:`get_connector` for a ``database`` source builds a connector whose SQL
delegate dereferences ``config["connection_string"]``.  Feeding it the raw
structured dict therefore raised ``KeyError: 'connection_string'`` and 500'd
``POST /sources/inspect``.

We assert:
  * a structured DB dict is translated so ``get_connector`` receives a config
    containing ``connection_string`` (we mock ``get_connector`` to record it).
  * a structured dict missing required fields → ``ValueError`` (NOT ``KeyError``)
    so the route maps it to 400.
  * a ``connection`` dict that *already* has ``connection_string`` (legacy /
    direct-connector callers) is passed through unchanged.
  * the error path never echoes the password or a ``://user:pass@`` URL.

``pytest-asyncio`` is in ``asyncio_mode = "auto"`` for this project, so the
``async def test_*`` functions need no explicit marker.
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.models.enums import SourceType
from src.services.source_inspection_service import SourceInspectionService

# No '@' on purpose: ``_build_database_config`` URL-quotes credentials, but the
# error-sanitiser regex (``://[^@\s]+@``) only strips up to the first '@', so a
# literal '@' inside the password would defeat a naive assertion.  Real
# connection strings never carry an unquoted '@'.
_PASSWORD = "s3cr3t-passw0rd"


def _service() -> SourceInspectionService:
    # The OpenAI client is only touched by the best-effort description step
    # (which swallows errors) — a bare MagicMock suffices.
    return SourceInspectionService(openai_client=MagicMock())


def _patch_get_connector(
    monkeypatch: pytest.MonkeyPatch, *, ok: bool = True
) -> dict[str, Any]:
    """Patch ``get_connector`` to record the (source_type, config) it received."""
    captured: dict[str, Any] = {}

    def _fake_get_connector(source_type: SourceType, config: dict[str, Any]) -> Any:
        captured["source_type"] = source_type
        captured["config"] = config
        connector = MagicMock()
        connector.test_connection = AsyncMock(return_value=ok)
        # No ``inspect_schema`` → schema summary stays {} (irrelevant here).
        del connector.inspect_schema
        return connector

    monkeypatch.setattr(
        "src.services.source_inspection_service.get_connector", _fake_get_connector
    )
    return captured


def _structured_pg_connection(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "db_type": "postgresql",
        "host": "db.internal",
        "port": 5432,
        "database": "analytics",
        "username": "reader",
        "password": _PASSWORD,
        "ssl_mode": "require",
    }
    base.update(overrides)
    return base


class TestDatabaseTranslation:
    async def test_structured_dict_translated_to_connection_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _patch_get_connector(monkeypatch, ok=True)
        svc = _service()

        await svc.inspect_source("database", _structured_pg_connection())

        cfg = captured["config"]
        assert captured["source_type"] is SourceType.DATABASE
        # The connector's SQL delegate reads ``connection_string`` — it MUST
        # be present (this is the KeyError that 500'd before the fix).
        assert "connection_string" in cfg
        assert cfg["connection_string"].startswith("postgresql+asyncpg://")
        assert "db.internal:5432/analytics" in cfg["connection_string"]
        assert cfg["db_type"] == "postgresql"
        assert cfg["ssl_mode"] == "require"
        # ``query`` is required for SQL dialects; inspect defaults it.
        assert cfg["query"] == "SELECT 1"
        # The raw structured keys must NOT have leaked into the connector cfg.
        assert "host" not in cfg
        assert "password" not in cfg

    async def test_caller_supplied_query_is_preserved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _patch_get_connector(monkeypatch, ok=True)
        svc = _service()

        await svc.inspect_source(
            "database",
            _structured_pg_connection(query="SELECT id, name FROM customers"),
        )

        assert captured["config"]["query"] == "SELECT id, name FROM customers"

    async def test_connection_string_dict_is_passed_through_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = _patch_get_connector(monkeypatch, ok=True)
        svc = _service()

        legacy = {
            "db_type": "postgresql",
            "connection_string": (
                "postgresql+asyncpg://reader:pw@db.internal:5432/analytics"
            ),
            "query": "SELECT 1",
        }
        await svc.inspect_source("database", legacy)

        # Passed through verbatim — no re-translation.
        assert captured["config"] == legacy

    async def test_missing_required_field_raises_valueerror_not_keyerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_get_connector(monkeypatch, ok=True)
        svc = _service()

        # ``host`` omitted → DatabaseConnectionConfig validation fails.
        bad = _structured_pg_connection()
        del bad["host"]

        with pytest.raises(ValueError) as excinfo:
            await svc.inspect_source("database", bad)
        # Must be ValueError (route → 400), never the raw KeyError.
        assert not isinstance(excinfo.value, KeyError)

    async def test_validation_error_message_never_leaks_password(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_get_connector(monkeypatch, ok=True)
        svc = _service()

        # An invalid dialect makes DatabaseConnectionConfig raise; the message
        # must not contain the password supplied alongside it.
        bad = _structured_pg_connection(db_type="not-a-real-dialect")

        with pytest.raises(ValueError) as excinfo:
            await svc.inspect_source("database", bad)
        msg = str(excinfo.value)
        assert _PASSWORD not in msg
        assert "://reader:" not in msg

    async def test_test_connection_false_raises_connectionerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_get_connector(monkeypatch, ok=False)
        svc = _service()

        with pytest.raises(ConnectionError):
            await svc.inspect_source("database", _structured_pg_connection())

    async def test_driver_exception_is_sanitised_to_connectionerror(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        svc = _service()

        def _fake_get_connector(
            source_type: SourceType, config: dict[str, Any]
        ) -> Any:
            connector = MagicMock()
            connector.test_connection = AsyncMock(
                side_effect=RuntimeError(
                    "connect failed: postgresql+asyncpg://reader:"
                    f"{_PASSWORD}@db.internal:5432/analytics"
                )
            )
            return connector

        monkeypatch.setattr(
            "src.services.source_inspection_service.get_connector",
            _fake_get_connector,
        )

        with pytest.raises(ConnectionError) as excinfo:
            await svc.inspect_source("database", _structured_pg_connection())
        msg = str(excinfo.value)
        assert _PASSWORD not in msg
        assert "://reader:" not in msg


class TestNonDatabaseUnaffected:
    async def test_file_source_short_circuits(self) -> None:
        svc = _service()
        result = await svc.inspect_source("pdf", {"object_key": "x"})
        assert result == {"description": "", "schema_summary": {}}

    async def test_unknown_source_type_raises_valueerror(self) -> None:
        svc = _service()
        with pytest.raises(ValueError):
            await svc.inspect_source("definitely-not-a-source", {})
