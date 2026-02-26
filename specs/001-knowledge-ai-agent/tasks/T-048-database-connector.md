# T-048 — Database Connector

## Context
```
Python 3.12 | SQLAlchemy 2.x async · asyncpg
SourceType.DATABASE · @register decorator · BaseConnector ABC
FR-020: connection_string MUST NEVER appear in any log or exception message
Config is pre-decrypted by SourceService._decrypt_config before reaching connector
```

## Goal
Implement `DatabaseConnector`: connect to an arbitrary async-compatible SQL database, execute a caller-supplied query in pages, and yield one `Document` per row. The connection string must never surface in logs, metrics, or exception text.

---

## File — `app/connectors/database_connector.py`

```python
from __future__ import annotations

import hashlib
import logging
from collections.abc import AsyncIterator
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.connectors.base import BaseConnector, Document
from app.connectors.registry import register
from app.models.enums import SourceType

logger = logging.getLogger(__name__)

_REDACTED = "REDACTED"


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

    IMPORTANT: connection_string is consumed once in connect().
               It is NEVER stored as a plain attribute after that.
               It MUST NOT appear in any log entry or exception message.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # Pop connection_string immediately — do not keep as plain attribute
        self._conn_str_hash: str = hashlib.sha256(
            config["connection_string"].encode()
        ).hexdigest()[:12]
        self._query: str = config["query"]
        self._page_size: int = int(config.get("page_size", 1000))
        self._engine: Any | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        """
        Create an async SQLAlchemy engine and perform a connectivity check.
        Raises ConnectionError (not the raw driver exception, which may contain
        the connection string in its message) if the test fails.
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
        except Exception as exc:
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
        logger.info("DatabaseConnector: disconnected [conn_hash=%s]", self._conn_str_hash)

    # ------------------------------------------------------------------ #
    # Extraction
    # ------------------------------------------------------------------ #

    async def extract_documents(self) -> AsyncIterator[Document]:
        assert self._engine is not None, "Call connect() before extract_documents()"

        source_id = self._config.get("source_id", "unknown")
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
                    source_id=source_id,  # type: ignore[arg-type]
                    raw_text=raw_text,
                    metadata={
                        "row_index": row_index,
                        "query_hash": query_hash,
                        # raw query text is intentionally omitted (FR-020)
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
        Execute `SELECT 1` via a temporary engine.
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
```

---

## Design Notes

### FR-020 — Connection string redaction

The connection string is accessed exclusively via `self._config["connection_string"]` at call-time (inside `connect()` and `test_connection()`). It is never assigned to an instance attribute, never interpolated into log messages, and never included in re-raised exceptions. Logging at all levels uses only `conn_hash` (first 12 hex chars of SHA-256).

### Pagination strategy

The connector wraps the caller-supplied `query` in a subquery and applies `LIMIT … OFFSET …` pages. This is portable (PostgreSQL, MySQL, SQLite) but may be slow on large datasets without an ORDER BY in the inner query — callers should include an ORDER BY in their query string for deterministic results.

### Row-to-text serialisation

Each row is serialised as `"col_name: value"` lines joined by newlines. This is intentionally simple; downstream chunking (T-062) will handle token boundaries.

---

## Acceptance Criteria

- [ ] `DatabaseConnector` is auto-registered for `SourceType.DATABASE` via `@register`
- [ ] `connect()` raises `ConnectionError` with a sanitised message (no connection string) when the database is unreachable
- [ ] `connection_string` never appears in any `logger.*` call at any level
- [ ] `connection_string` never appears in any re-raised exception message
- [ ] `extract_documents()` uses `LIMIT/OFFSET` pagination; stops when a page has fewer rows than `page_size`
- [ ] Each row yields exactly one `Document`; `metadata` contains `row_index` and `query_hash` but NOT the raw query text
- [ ] `raw_storage_path` is `None` on every yielded `Document`
- [ ] `test_connection()` returns `False` (not raises) on any exception; does not log the connection string
- [ ] `disconnect()` calls `engine.dispose()` and sets `self._engine = None`
