"""Unit tests for DatabaseConnector (T-057).

FR-020 compliance:
  - ConnectionError message must NOT contain the connection string.
  - extract_documents() metadata must NOT include query text — only query_hash.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.connectors.base import Document

# Tests target the SQL-only implementation directly (the public
# ``DatabaseConnector`` is now a thin db_type-router that delegates here).
from src.connectors.database_connector import (
    SqlDatabaseConnector as DatabaseConnector,
)
from src.connectors.database_connector import (
    _sanitise,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_SOURCE_ID = str(uuid.uuid4())
_CONN_STR = "postgresql+asyncpg://user:secret@localhost:5432/testdb"
_QUERY = "SELECT id, content FROM documents"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connector(extra: dict[str, Any] | None = None) -> DatabaseConnector:
    cfg: dict[str, Any] = {
        "connection_string": _CONN_STR,
        "query": _QUERY,
        "source_id": _SOURCE_ID,
    }
    if extra:
        cfg.update(extra)
    return DatabaseConnector(config=cfg)


def _mock_engine(rows_sequence: list[list[dict[str, Any]]]) -> MagicMock:
    """
    Build a mock async engine whose connect() returns a context manager that
    yields a mock connection executing paged queries in order.
    rows_sequence is a list of page results; each element is the list of
    row-mapping dicts returned for that OFFSET page.
    """
    engine = MagicMock()
    engine.dispose = AsyncMock()

    # Each call to conn.execute() returns a result whose mappings().all()
    # returns the next page.  We feed pages one by one.
    call_count = [0]

    async def fake_execute(sql: Any, params: dict | None = None) -> MagicMock:  # noqa: ANN401
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        rows = rows_sequence[idx] if idx < len(rows_sequence) else []
        result.mappings.return_value.all.return_value = rows
        return result

    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(side_effect=fake_execute)

    # Context manager for `engine.connect()`
    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect = MagicMock(return_value=conn_ctx)

    return engine


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


def test_constructor_does_not_store_connection_string_plainly() -> None:
    conn = _make_connector()
    # The plain connection string must not exist as an attribute value
    for attr_value in vars(conn).values():
        assert attr_value != _CONN_STR, (
            "connection_string stored in plain text — violates FR-020"
        )


def test_constructor_stores_hash() -> None:
    conn = _make_connector()
    assert hasattr(conn, "_conn_str_hash")
    assert len(conn._conn_str_hash) > 0  # noqa: SLF001


def test_constructor_stores_query() -> None:
    conn = _make_connector()
    assert conn._query == _QUERY  # noqa: SLF001


def test_constructor_default_page_size() -> None:
    conn = _make_connector()
    assert conn._page_size == 1000  # noqa: SLF001


def test_constructor_custom_page_size() -> None:
    conn = _make_connector(extra={"page_size": 250})
    assert conn._page_size == 250  # noqa: SLF001


# ---------------------------------------------------------------------------
# connect — happy path
# ---------------------------------------------------------------------------


async def test_connect_calls_create_async_engine() -> None:
    conn = _make_connector()
    engine = _mock_engine([])
    # call_count reset for connect-only test
    conn_ctx = MagicMock()
    select1 = MagicMock()
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(return_value=select1)
    conn_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect = MagicMock(return_value=conn_ctx)

    with patch("src.connectors.database_connector.create_async_engine", return_value=engine) as mock_create:
        await conn.connect()

    mock_create.assert_called_once()
    assert conn._engine is not None  # noqa: SLF001


async def test_connect_asyncpg_passes_server_settings_connect_args() -> None:
    # Default _CONN_STR is a postgresql+asyncpg URL → hardening flows via
    # connect_args server_settings (the URL itself is unchanged).
    conn = _make_connector(extra={"db_type": "postgresql"})
    engine = _mock_engine([])
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(return_value=MagicMock())
    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect = MagicMock(return_value=conn_ctx)

    with patch(
        "src.connectors.database_connector.create_async_engine",
        return_value=engine,
    ) as mock_create:
        await conn.connect()

    connect_args = mock_create.call_args.kwargs["connect_args"]
    assert "server_settings" in connect_args
    assert (
        connect_args["server_settings"]["default_transaction_read_only"] == "on"
    )


async def test_connect_libpq_passes_empty_connect_args() -> None:
    # A libpq (non-asyncpg) postgres URL hardens via the URL options=, so
    # connect_args must stay empty.
    conn = _make_connector(
        extra={
            "db_type": "postgresql",
            "connection_string": "postgresql://user:secret@localhost:5432/testdb",
        }
    )
    engine = _mock_engine([])
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(return_value=MagicMock())
    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect = MagicMock(return_value=conn_ctx)

    with patch(
        "src.connectors.database_connector.create_async_engine",
        return_value=engine,
    ) as mock_create:
        await conn.connect()

    assert mock_create.call_args.kwargs["connect_args"] == {}
    # Hardening rides in the URL instead (passed positionally as conn_str;
    # the options= value is URL-encoded, so decode before the substring check).
    from urllib.parse import unquote

    assert (
        "default_transaction_read_only=on"
        in unquote(mock_create.call_args.args[0])
    )


async def test_connect_raises_connection_error_on_failure() -> None:
    conn = _make_connector()

    failing_engine = MagicMock()
    conn_ctx = MagicMock()
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(side_effect=Exception("authentication failed password=secret"))
    conn_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    failing_engine.connect = MagicMock(return_value=conn_ctx)

    with patch("src.connectors.database_connector.create_async_engine", return_value=failing_engine):
        with pytest.raises(ConnectionError):
            await conn.connect()


async def test_connect_error_message_does_not_contain_connection_string() -> None:
    """FR-020: sanitised error must not leak credentials."""
    conn = _make_connector()

    failing_engine = MagicMock()
    conn_ctx = MagicMock()
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(side_effect=Exception("db error"))
    conn_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    failing_engine.connect = MagicMock(return_value=conn_ctx)

    with patch("src.connectors.database_connector.create_async_engine", return_value=failing_engine):
        try:
            await conn.connect()
        except ConnectionError as exc:
            assert _CONN_STR not in str(exc), (
                "ConnectionError message leaks connection string — violates FR-020"
            )
        else:
            pytest.fail("Expected ConnectionError was not raised")


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------


async def test_disconnect_disposes_engine() -> None:
    conn = _make_connector()
    mock_engine = MagicMock()
    mock_engine.dispose = AsyncMock()
    conn._engine = mock_engine  # noqa: SLF001

    await conn.disconnect()

    mock_engine.dispose.assert_awaited_once()
    assert conn._engine is None  # noqa: SLF001


async def test_disconnect_without_connect_is_safe() -> None:
    conn = _make_connector()
    await conn.disconnect()  # should not raise


# ---------------------------------------------------------------------------
# extract_documents — guard
# ---------------------------------------------------------------------------


async def test_extract_documents_raises_without_connect() -> None:
    conn = _make_connector()
    with pytest.raises(AssertionError):
        async for _ in conn.extract_documents():
            pass


# ---------------------------------------------------------------------------
# extract_documents — happy path (single page)
# ---------------------------------------------------------------------------


async def test_extract_documents_yields_one_doc_per_row() -> None:
    conn = _make_connector()
    rows = [{"id": 1, "content": "hello"}, {"id": 2, "content": "world"}]
    # Page 1 returns 2 rows (< page_size=1000); next call implied empty
    engine = _mock_engine([rows])
    conn._engine = engine  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert len(docs) == 2


async def test_extract_documents_doc_type() -> None:
    conn = _make_connector()
    rows = [{"id": 1, "content": "hello"}]
    conn._engine = _mock_engine([rows])  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert isinstance(docs[0], Document)


async def test_extract_documents_source_id_is_uuid() -> None:
    conn = _make_connector()
    rows = [{"id": 1, "content": "a"}]
    conn._engine = _mock_engine([rows])  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert isinstance(docs[0].source_id, uuid.UUID)
    assert docs[0].source_id == uuid.UUID(_SOURCE_ID)


async def test_extract_documents_metadata_has_row_index() -> None:
    conn = _make_connector()
    rows = [{"id": 1, "content": "a"}, {"id": 2, "content": "b"}]
    conn._engine = _mock_engine([rows])  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert docs[0].metadata["row_index"] == 0
    assert docs[1].metadata["row_index"] == 1


async def test_extract_documents_metadata_has_query_hash() -> None:
    conn = _make_connector()
    rows = [{"id": 1, "content": "a"}]
    conn._engine = _mock_engine([rows])  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert "query_hash" in docs[0].metadata


async def test_extract_documents_metadata_does_not_contain_query_text() -> None:
    """FR-020: raw query must not appear in any metadata field."""
    conn = _make_connector()
    rows = [{"id": 1, "content": "a"}]
    conn._engine = _mock_engine([rows])  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    for key, value in docs[0].metadata.items():
        assert _QUERY not in str(value), (
            f"Query text found in metadata[{key!r}] — violates FR-020"
        )
    assert "query" not in docs[0].metadata or docs[0].metadata.get("query") != _QUERY


async def test_extract_documents_raw_text_contains_column_values() -> None:
    conn = _make_connector()
    rows = [{"id": 42, "content": "meaningful text"}]
    conn._engine = _mock_engine([rows])  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert "meaningful text" in docs[0].raw_text


# ---------------------------------------------------------------------------
# extract_documents — pagination (two full pages + empty)
# ---------------------------------------------------------------------------


async def test_extract_documents_paginates_multiple_pages() -> None:
    conn = _make_connector(extra={"page_size": 3})

    page1 = [{"id": i, "v": str(i)} for i in range(3)]
    page2 = [{"id": i, "v": str(i)} for i in range(3, 6)]
    page3: list[dict[str, Any]] = []  # empty — signals end

    # Build a custom engine that returns pages + final empty without SELECT 1 skew
    engine = MagicMock()
    engine.dispose = AsyncMock()
    call_count = [0]
    pages = [page1, page2, page3]

    async def paged_execute(sql: Any, params: dict | None = None) -> MagicMock:  # noqa: ANN401
        result = MagicMock()
        idx = call_count[0]
        call_count[0] += 1
        page = pages[idx] if idx < len(pages) else []
        result.mappings.return_value.all.return_value = page
        return result

    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(side_effect=paged_execute)
    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect = MagicMock(return_value=conn_ctx)

    conn._engine = engine  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert len(docs) == 6


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


async def test_test_connection_returns_true_on_success() -> None:
    conn = _make_connector()
    engine = MagicMock()
    engine.dispose = AsyncMock()
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(return_value=MagicMock())
    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect = MagicMock(return_value=conn_ctx)

    with patch("src.connectors.database_connector.create_async_engine", return_value=engine):
        result = await conn.test_connection()

    assert result is True


async def test_test_connection_returns_false_on_failure() -> None:
    conn = _make_connector()
    engine = MagicMock()
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(side_effect=Exception("connection refused"))
    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect = MagicMock(return_value=conn_ctx)

    with patch("src.connectors.database_connector.create_async_engine", return_value=engine):
        result = await conn.test_connection()

    assert result is False


async def test_test_connection_never_raises() -> None:
    conn = _make_connector()
    engine = MagicMock()
    fake_conn = AsyncMock()
    fake_conn.execute = AsyncMock(side_effect=RuntimeError("unexpected"))
    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect = MagicMock(return_value=conn_ctx)

    with patch("src.connectors.database_connector.create_async_engine", return_value=engine):
        result = await conn.test_connection()

    assert isinstance(result, bool)
    assert result is False


async def test_test_connection_connection_string_not_in_error_context() -> None:
    """FR-020: test_connection must not log or raise with connection string."""
    import logging

    conn = _make_connector()
    engine = MagicMock()
    fake_conn = AsyncMock()
    error_with_creds = Exception(f"auth failed for {_CONN_STR}")
    fake_conn.execute = AsyncMock(side_effect=error_with_creds)
    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)
    engine.connect = MagicMock(return_value=conn_ctx)

    # Capture log output during test_connection
    import io

    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    db_logger = logging.getLogger("src.connectors.database_connector")
    db_logger.addHandler(handler)

    with patch("src.connectors.database_connector.create_async_engine", return_value=engine):
        result = await conn.test_connection()

    db_logger.removeHandler(handler)

    # Result must be False
    assert result is False
    # Logged output must NOT include the raw connection string
    log_output = log_stream.getvalue()
    assert _CONN_STR not in log_output, (
        "Connection string found in log output — violates FR-020"
    )


# ---------------------------------------------------------------------------
# Async context manager
# ---------------------------------------------------------------------------


async def test_async_context_manager_calls_connect_disconnect() -> None:
    conn = _make_connector()

    with patch.object(conn, "connect", new_callable=AsyncMock) as mock_connect, \
         patch.object(conn, "disconnect", new_callable=AsyncMock) as mock_disconnect:
        async with conn:
            mock_connect.assert_called_once()
        mock_disconnect.assert_called_once()


# ---------------------------------------------------------------------------
# _sanitise — credential / DSN redaction (FR-020) regression tests
# ---------------------------------------------------------------------------


class TestSanitise:
    """Lock in the credential-redaction fix so it can never silently regress."""

    def test_redacts_password_containing_at_sign(self) -> None:
        # Regression: a password with '@' must be FULLY stripped, not just up to
        # the first '@' (the old `://[^@\\s/]+@` regex leaked the tail).
        out = _sanitise(
            "auth failed for postgresql+asyncpg://user:p@ss@host:5432/db"
        )
        assert "p@ss" not in out
        assert "pass" not in out
        assert "://***@" in out

    def test_redacts_simple_url_credentials(self) -> None:
        out = _sanitise("could not connect to postgresql://admin:secret@db/app")
        assert "secret" not in out
        assert "://***@" in out

    def test_redacts_dsn_keyword_fragments(self) -> None:
        out = _sanitise(
            "connection failed: host=db port=5432 user=admin "
            "password=hunter2 dbname=app"
        )
        assert "hunter2" not in out
        assert "password=<redacted>" in out
        assert "admin" not in out  # user=<redacted>

    def test_masks_bare_host_port(self) -> None:
        out = _sanitise("timeout connecting to internal-db.example.com:5432")
        assert "internal-db.example.com:5432" not in out
        assert "<host>:<port>" in out

    def test_leaves_credential_free_text_untouched(self) -> None:
        # No over-redaction of an innocuous message (no URL, no kv, no host:port).
        msg = "relation \"documents\" does not exist"
        assert _sanitise(msg) == msg
