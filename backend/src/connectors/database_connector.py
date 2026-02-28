from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from src.connectors.base import BaseConnector, Document
from src.connectors.registry import register
from src.models.enums import SourceType

logger = logging.getLogger(__name__)


@register(SourceType.DATABASE)
class DatabaseConnector(BaseConnector):
    """
    Connector for arbitrary SQL databases accessible via an asyncpg-compatible
    connection string.

    Expected *config* keys (pre-decrypted by SourceService):
        connection_string (str, required) — async-compatible URL, e.g.
                                            "postgresql+asyncpg://user:pass@host/db"
        query             (str, required) — single SELECT statement; must return
                                            named columns
        page_size         (int, optional, default 1000) — rows per OFFSET page
        source_id         (str, optional) — UUID string for Document.source_id

    IMPORTANT: connection_string is consumed once in connect().
               It is NEVER stored as a plain attribute after that.
               It MUST NOT appear in any log entry or exception message.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # Hash the connection string immediately — never store it plain
        self._conn_str_hash: str = hashlib.sha256(
            config["connection_string"].encode()
        ).hexdigest()[:12]
        self._query: str = config["query"]
        self._page_size: int = int(config.get("page_size", 1000))
        self._source_id: str | None = config.get("source_id")
        self._engine: Any | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        """
        Create an async SQLAlchemy engine and perform a connectivity check.
        Raises ConnectionError (not the raw driver exception, which may contain
        the connection string in its message) if the test SELECT 1 fails.
        """
        conn_str: str = self._config["connection_string"]
        try:
            engine = create_async_engine(
                conn_str,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=0,
            )
            async with engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
        except Exception:
            # Re-raise a sanitised error — original exc may contain credentials
            raise ConnectionError(
                f"Database connection failed for source "
                f"[conn_hash={self._conn_str_hash}]: see server logs for details"
            ) from None

        self._engine = engine
        logger.info(
            "DatabaseConnector: connected [conn_hash=%s]",
            self._conn_str_hash,
        )

    async def disconnect(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        logger.info(
            "DatabaseConnector: disconnected [conn_hash=%s]",
            self._conn_str_hash,
        )

    # ------------------------------------------------------------------ #
    # Extraction
    # ------------------------------------------------------------------ #

    async def extract_documents(  # type: ignore[override]
        self,
    ) -> AsyncIterator[Document]:
        assert self._engine is not None, "Call connect() before extract_documents()"

        resolved_source_id: uuid.UUID = (
            uuid.UUID(self._source_id) if self._source_id else uuid.uuid4()
        )
        query_hash = hashlib.sha256(self._query.encode()).hexdigest()[:12]
        row_index = 0
        offset = 0

        logger.info(
            "DatabaseConnector: starting extraction "
            "[query_hash=%s page_size=%d conn_hash=%s]",
            query_hash,
            self._page_size,
            self._conn_str_hash,
        )

        while True:
            paged_sql = sa.text(
                f"SELECT * FROM ({self._query}) AS _q "  # noqa: S608
                f"LIMIT :limit OFFSET :offset"
            )
            async with self._engine.connect() as conn:
                result = await conn.execute(
                    paged_sql,
                    {"limit": self._page_size, "offset": offset},
                )
                rows = result.mappings().all()

            if not rows:
                logger.info(
                    "DatabaseConnector: extraction complete — %d rows yielded "
                    "[query_hash=%s]",
                    row_index,
                    query_hash,
                )
                break

            for row in rows:
                raw_text = "\n".join(
                    f"{col}: {val}" for col, val in row.items()
                )
                yield Document(
                    source_id=resolved_source_id,
                    raw_text=raw_text,
                    metadata={
                        "row_index": row_index,
                        "query_hash": query_hash,
                        # raw query text intentionally omitted (FR-020)
                    },
                    raw_storage_path=None,
                )
                row_index += 1

            offset += self._page_size
            if len(rows) < self._page_size:
                # Last page — no need for another round-trip
                logger.info(
                    "DatabaseConnector: final page reached — %d rows total "
                    "[query_hash=%s]",
                    row_index,
                    query_hash,
                )
                break

    # ------------------------------------------------------------------ #
    # test_connection
    # ------------------------------------------------------------------ #

    async def test_connection(self) -> bool:
        """
        Execute SELECT 1 via a temporary engine.
        Returns False (not raises) on any failure.
        connection_string MUST NOT appear in any log or exception message.
        """
        conn_str: str = self._config["connection_string"]
        try:
            engine = create_async_engine(conn_str, pool_size=1, max_overflow=0)
            async with engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
            await engine.dispose()
            return True
        except Exception:
            # Log WITHOUT the connection string
            logger.warning(
                "DatabaseConnector.test_connection failed [conn_hash=%s]",
                self._conn_str_hash,
            )
            return False
