"""Unit tests for MongoDBConnector — T-090."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.connectors.mongodb_connector import MongoDBConnector
from src.core.exceptions import ServiceUnavailableError


def _make_connector(uri="mongodb://localhost:27017", db="testdb") -> MongoDBConnector:
    return MongoDBConnector(config={"uri": uri, "database": db})


def _make_mock_motor_client(ping_ok=True):
    """Return a mock that mimics AsyncIOMotorClient well enough."""
    mock_client = MagicMock()
    if ping_ok:
        mock_client.admin.command = AsyncMock(return_value={"ok": 1})
    else:
        mock_client.admin.command = AsyncMock(
            side_effect=Exception("connection refused")
        )
    return mock_client


# ---------------------------------------------------------------------------
# TestConnect
# ---------------------------------------------------------------------------

class TestConnect:
    async def test_connect_success_stores_client(self):
        """connect() stores the motor client on success."""
        connector = _make_connector()
        mock_client = _make_mock_motor_client(ping_ok=True)

        with patch(
            "src.connectors.mongodb_connector.AsyncIOMotorClient",
            return_value=mock_client,
        ):
            await connector.connect()

        assert connector._client is mock_client

    async def test_connect_failed_ping_raises_service_unavailable(self):
        """connect() raises ServiceUnavailableError and resets _client on ping failure."""
        connector = _make_connector()
        mock_client = _make_mock_motor_client(ping_ok=False)

        with patch(
            "src.connectors.mongodb_connector.AsyncIOMotorClient",
            return_value=mock_client,
        ):
            with pytest.raises(ServiceUnavailableError):
                await connector.connect()

        assert connector._client is None


# ---------------------------------------------------------------------------
# TestFetchDocuments
# ---------------------------------------------------------------------------

class TestFetchDocuments:
    async def test_fetch_documents_raises_service_unavailable_when_no_client(self):
        """fetch_documents raises ServiceUnavailableError when _client is None."""
        connector = _make_connector()
        # _client is None by default

        with pytest.raises(ServiceUnavailableError):
            await connector.fetch_documents(collection="docs", query={})

    async def test_fetch_documents_returns_list_of_dicts(self):
        """fetch_documents returns a list of documents from the collection."""
        connector = _make_connector()

        doc1 = {"_id": "aaa", "title": "Hello"}
        doc2 = {"_id": "bbb", "title": "World"}

        # Build a mock cursor
        mock_cursor = MagicMock()
        mock_cursor.to_list = AsyncMock(return_value=[doc1, doc2])

        # Build a mock collection
        mock_collection = MagicMock()
        mock_collection.find = MagicMock(return_value=mock_cursor)

        # Build a mock database
        mock_db = MagicMock()
        mock_db.__getitem__ = MagicMock(return_value=mock_collection)
        mock_db.get_collection = MagicMock(return_value=mock_collection)

        # Build a mock client
        mock_client = MagicMock()
        mock_client.__getitem__ = MagicMock(return_value=mock_db)
        mock_client.get_database = MagicMock(return_value=mock_db)

        connector._client = mock_client

        result = await connector.fetch_documents(collection="docs", query={})

        assert doc1 in result
        assert doc2 in result
