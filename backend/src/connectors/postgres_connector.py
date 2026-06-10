"""PostgreSQL connector — executes arbitrary SQL and streams document rows.

Requires ``asyncpg``; the package is installed in the project venv.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import asyncpg  # asyncpg 0.31.0 — installed ✅

from src.connectors.base import BaseConnector, Document
from src.core.exceptions import BadRequestError, ServiceUnavailableError
from src.services.db_safety import redact_dsn

# ---------------------------------------------------------------------------
# Credential / DSN redaction (FR-020)
# ---------------------------------------------------------------------------
# asyncpg raises errors whose ``str(exc)`` can embed the connection DSN
# (``scheme://user:pass@host`` URL, ``password=...`` / ``host=...`` key-value
# pairs, bare ``host:port``). Those exceptions must NEVER reach a log line or a
# user-facing error envelope. Delegates to the single canonical hardened
# redactor (:func:`src.services.db_safety.redact_dsn`); the module-local alias
# preserves the existing call sites.
_sanitise = redact_dsn


class PostgresConnector(BaseConnector):
    """Connects to a PostgreSQL database and fetches rows as documents.

    Expected *config* keys:

    * ``host`` – database host
    * ``port`` – database port (default ``5432``)
    * ``database`` – database name
    * ``user`` – login username
    * ``password`` – login password
    * ``query`` – SQL to execute when :meth:`extract_documents` is used
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._conn: asyncpg.Connection | None = None

    # ------------------------------------------------------------------
    # BaseConnector interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open a connection to PostgreSQL.

        Raises:
            :exc:`~src.core.exceptions.ServiceUnavailableError`: When the
                connection cannot be established.
        """
        try:
            self._conn = await asyncpg.connect(
                host=self._config.get("host", "localhost"),
                port=self._config.get("port", 5432),
                database=self._config.get("database", ""),
                user=self._config.get("user", ""),
                password=self._config.get("password", ""),
            )
        except Exception as exc:
            # ``str(exc)`` from asyncpg can embed the DSN (host/user/password);
            # scrub before it reaches a user-facing error envelope (FR-020).
            raise ServiceUnavailableError(
                f"Failed to connect to PostgreSQL: {_sanitise(exc)}"
            ) from None

    async def disconnect(self) -> None:
        """Close the underlying ``asyncpg`` connection if open."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def extract_documents(self) -> AsyncIterator[Document]:  # type: ignore[override]
        """Yield rows returned by the configured *query* as :class:`~src.connectors.base.Document` objects.

        Raises:
            :exc:`~src.core.exceptions.BadRequestError`: When the query fails.
        """
        query = self._config.get("query", "")
        rows = await self.fetch_rows(query)
        for row in rows:
            yield Document(content=str(row), metadata=row)

    async def test_connection(self) -> bool:
        """Verify connectivity using the active connection.

        Returns:
            ``True`` when a live connection is established, ``False`` otherwise.
        """
        if self._conn is None:
            return False
        try:
            await self._conn.fetchval("SELECT 1")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Extended interface
    # ------------------------------------------------------------------

    async def fetch_rows(self, query: str) -> list[dict[str, Any]]:
        """Execute *query* and return all rows as plain dicts.

        Args:
            query: SQL query to execute.

        Returns:
            List of row mappings.

        Raises:
            :exc:`~src.core.exceptions.BadRequestError`: When the query fails
                (e.g. syntax error, unknown table).
        """
        if self._conn is None:
            raise ServiceUnavailableError("PostgresConnector: not connected.")
        try:
            records = await self._conn.fetch(query)
            return [dict(record) for record in records]
        except Exception as exc:
            # ``str(exc)`` from asyncpg can embed the DSN (host/user/password);
            # scrub before it reaches a user-facing error envelope (FR-020).
            raise BadRequestError(
                f"PostgreSQL query error: {_sanitise(exc)}"
            ) from None
