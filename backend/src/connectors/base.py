"""Base connector abstractions shared by all concrete connectors (T-045).

Defines:
  - ``Document``       — value object yielded by every connector
  - ``BaseConnector``  — ABC that all connector implementations must subclass
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.schemas.raw_document import RawDocument

from pydantic import BaseModel, Field

# ------------------------------------------------------------------ #
# Document value object
# ------------------------------------------------------------------ #


class Document(BaseModel):
    """
    Unit of extracted content produced by a connector and passed downstream
    to the chunker → embedder → vector store pipeline.

    ``raw_storage_path`` is the MinIO object key where the raw file/page has been
    archived, or ``None`` if the connector streams inline text only.
    """

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    source_id: uuid.UUID
    raw_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_storage_path: str | None = None


# ------------------------------------------------------------------ #
# BaseConnector ABC
# ------------------------------------------------------------------ #


class BaseConnector(ABC):
    """
    Abstract base for all source connectors.

    Concrete implementations MUST be registered via the ``@register`` decorator
    in ``src/connectors/registry.py`` before ``get_connector`` can return them.

    Usage (async context manager — preferred)::

        async with get_connector(source_type, config) as conn:
            async for doc in conn.extract_documents():
                ...

    Usage (manual lifecycle)::

        conn = get_connector(source_type, config)
        await conn.connect()
        ...
        await conn.disconnect()
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config

    # ---------------------------------------------------------------- #
    # Abstract interface — all subclasses implement these
    # ---------------------------------------------------------------- #

    @abstractmethod
    async def connect(self) -> None:
        """
        Establish the connection to the external system.
        Raise ``ConnectionError`` (or a subclass) on failure.
        """

    @abstractmethod
    def extract_documents(self) -> AsyncIterator[Document]:
        """
        Yield ``Document`` objects one at a time.
        Allows the pipeline to start processing before extraction completes.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Release all resources held by the connector.
        Must be idempotent — safe to call even if ``connect`` was never called.
        """

    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Attempt a lightweight connectivity check.
        Return ``True`` on success, ``False`` on any failure.
        MUST NOT raise — all exceptions must be caught internally.
        """

    async def fetch_documents(self) -> list[RawDocument]:
        """
        Return all documents from this source as a flat list of
        :class:`~src.schemas.raw_document.RawDocument` objects.

        The default implementation raises ``NotImplementedError``; concrete
        connectors that back the Celery sync pipeline should override this
        method instead of (or in addition to) ``extract_documents``.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement fetch_documents()"
        )

    # ---------------------------------------------------------------- #
    # Async context manager support
    # ---------------------------------------------------------------- #

    async def __aenter__(self) -> BaseConnector:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.disconnect()
