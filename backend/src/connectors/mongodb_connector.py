"""MongoDB connector — queries collections via Motor (async driver).

*motor* is **not** installed in this environment; the import is guarded so
tests can patch :data:`AsyncIOMotorClient` without a real install.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    AsyncIOMotorClient = None  # type: ignore[assignment,misc]

from src.connectors.base import BaseConnector, Document
from src.core.exceptions import ServiceUnavailableError


class MongoDBConnector(BaseConnector):
    """Connects to MongoDB and fetches documents from a named collection.

    Expected *config* keys:

    * ``uri`` – MongoDB connection string (e.g. ``"mongodb://host:27017"``)
    * ``database`` – database name
    * ``collection`` – default collection to query when using
      :meth:`extract_documents`
    * ``query`` – optional filter dict applied during
      :meth:`extract_documents` (default: ``{}``)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._client: Any = None  # AsyncIOMotorClient | None

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open a Motor client and verify connectivity with a *ping*.

        Raises:
            :exc:`~src.core.exceptions.ServiceUnavailableError`: When the
                ping fails or the client cannot be instantiated.
        """
        uri = self._config.get("uri", "mongodb://localhost:27017")
        try:
            self._client = AsyncIOMotorClient(uri)  # type: ignore[misc]
            await self._client.admin.command("ping")
        except Exception as exc:
            self._client = None
            raise ServiceUnavailableError(
                f"Failed to connect to MongoDB: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        """Close the Motor client if open."""
        if self._client is not None:
            self._client.close()
            self._client = None

    async def extract_documents(self) -> AsyncIterator[Document]:  # type: ignore[override]
        """Yield documents from the configured collection as
        :class:`~src.connectors.base.Document` instances.
        """
        collection = self._config.get("collection", "")
        query: dict[str, Any] = self._config.get("query", {})
        raw = await self.fetch_documents(collection, query)
        for doc in raw:
            yield Document(content=str(doc), metadata=doc)

    async def test_connection(self) -> bool:
        """Verify connectivity by opening a client, pinging, and closing.

        Returns:
            ``True`` when successful, ``False`` otherwise.
        """
        uri = self._config.get("uri", "mongodb://localhost:27017")
        try:
            client = AsyncIOMotorClient(uri)  # type: ignore[misc]
            await client.admin.command("ping")
            client.close()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Extended interface
    # ------------------------------------------------------------------

    async def fetch_documents(
        self, collection: str, query: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Retrieve documents from *collection* matching *query*.

        Args:
            collection: Name of the MongoDB collection.
            query: Filter document (same format as PyMongo/Motor ``find``).

        Returns:
            List of document dicts (``_id`` preserved as returned by Motor).

        Raises:
            :exc:`~src.core.exceptions.ServiceUnavailableError`: When the
                client is not connected.
        """
        if self._client is None:
            raise ServiceUnavailableError("MongoDBConnector: not connected.")
        db_name: str = self._config.get("database", "")
        db = self._client[db_name]
        col = db[collection]
        cursor = col.find(query)
        return await cursor.to_list(length=None)
