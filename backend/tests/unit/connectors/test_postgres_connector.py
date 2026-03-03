"""Unit tests for PostgresConnector — T-090."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.connectors.postgres_connector import PostgresConnector
from src.core.exceptions import BadRequestError, ServiceUnavailableError


def _make_connector(dsn="postgresql://localhost/test") -> PostgresConnector:
    return PostgresConnector(config={"dsn": dsn})


# ---------------------------------------------------------------------------
# TestConnect
# ---------------------------------------------------------------------------

class TestConnect:
    async def test_connect_success(self):
        """connect() stores a connection when asyncpg.connect succeeds."""
        connector = _make_connector()
        mock_conn = AsyncMock()

        with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
            await connector.connect()

        assert connector._conn is mock_conn

    async def test_connect_raises_service_unavailable_on_error(self):
        """connect() raises ServiceUnavailableError when asyncpg.connect fails."""
        connector = _make_connector()

        with patch(
            "asyncpg.connect",
            new=AsyncMock(side_effect=Exception("connection refused")),
        ):
            with pytest.raises(ServiceUnavailableError):
                await connector.connect()


# ---------------------------------------------------------------------------
# TestFetchRows
# ---------------------------------------------------------------------------

class TestFetchRows:
    async def test_fetch_rows_returns_list_of_dicts(self):
        """fetch_rows returns a list of row dicts when connected."""
        connector = _make_connector()
        mock_conn = AsyncMock()
        row1 = {"id": str(uuid.uuid4()), "name": "Alice"}
        row2 = {"id": str(uuid.uuid4()), "name": "Bob"}
        mock_conn.fetch = AsyncMock(return_value=[row1, row2])
        connector._conn = mock_conn

        result = await connector.fetch_rows("SELECT id, name FROM users")

        assert result == [row1, row2]

    async def test_fetch_rows_raises_bad_request_on_query_error(self):
        """fetch_rows raises BadRequestError when the query fails."""
        connector = _make_connector()
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(
            side_effect=Exception("syntax error near 'SELCT'")
        )
        connector._conn = mock_conn

        with pytest.raises(BadRequestError):
            await connector.fetch_rows("SELCT * FROM users")

    async def test_fetch_rows_raises_service_unavailable_when_not_connected(self):
        """fetch_rows raises ServiceUnavailableError when _conn is None."""
        connector = _make_connector()
        # _conn is None by default

        with pytest.raises(ServiceUnavailableError):
            await connector.fetch_rows("SELECT 1")


# ---------------------------------------------------------------------------
# TestTestConnection
# ---------------------------------------------------------------------------

class TestTestConnection:
    async def test_test_connection_returns_true_when_connected(self):
        """test_connection returns True when _conn is set."""
        connector = _make_connector()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=1)
        connector._conn = mock_conn

        result = await connector.test_connection()

        assert result is True

    async def test_test_connection_returns_false_when_not_connected(self):
        """test_connection returns False when _conn is None."""
        connector = _make_connector()

        result = await connector.test_connection()

        assert result is False
