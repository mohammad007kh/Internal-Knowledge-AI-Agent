from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from src.connectors.base import BaseConnector, Document
from src.connectors.registry import register
from src.models.enums import SourceType
from src.services.db_safety import validate_sql

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.services.db_introspection.schema_doc import SchemaDocument

logger = logging.getLogger(__name__)


@register(SourceType.DATABASE)
class DatabaseConnector(BaseConnector):
    """Top-level router for the consolidated ``database`` source type.

    The single ``SourceType.DATABASE`` enum value covers four dialects:
    PostgreSQL / MySQL / SQL Server (all SQL) and MongoDB (NoSQL).  This
    router class inspects ``config["db_type"]`` and delegates the entire
    BaseConnector contract (connect / extract / disconnect / test_connection)
    to the appropriate concrete implementation:

      * ``"postgresql" | "mysql" | "mssql"`` → :class:`SqlDatabaseConnector`
        — SQLAlchemy async engine + paginated SELECT.
      * ``"mongodb"`` → :class:`~src.connectors.mongodb_connector.MongoDBConnector`
        — Motor client + collection iteration.

    Decision rationale: the registry keys connectors by :class:`SourceType`
    only.  Adding a sub-discriminator would require registry surgery; routing
    inside the registered class keeps the registry simple and lets MongoDB
    stay fully decoupled (no separate registration entry).

    Expected *config* keys (pre-decrypted by SourceService):
        db_type (str, required) — "postgresql" | "mysql" | "mssql" | "mongodb"
        plus the dialect-specific keys consumed by the delegate (see each
        delegate's docstring).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        db_type = config.get("db_type")
        if db_type == "mongodb":
            # Local import — avoids importing motor at module load when the
            # mongo driver is not installed in this environment.
            from src.connectors.mongodb_connector import (  # noqa: PLC0415
                MongoDBConnector,
            )

            self._delegate: BaseConnector = MongoDBConnector(config)
        elif db_type in {"postgresql", "mysql", "mssql"}:
            self._delegate = SqlDatabaseConnector(config)
        elif db_type is None and "connection_string" in config:
            # Legacy config (pre-consolidation) — assume SQL dialect.
            self._delegate = SqlDatabaseConnector(config)
        else:
            raise ValueError(
                f"Unsupported db_type for database connector: {db_type!r}"
            )

    async def connect(self) -> None:
        await self._delegate.connect()

    async def disconnect(self) -> None:
        await self._delegate.disconnect()

    def extract_documents(self) -> AsyncIterator[Document]:  # type: ignore[override]
        return self._delegate.extract_documents()

    async def test_connection(self) -> bool:
        return await self._delegate.test_connection()

    async def study_schema(self) -> SchemaDocument:
        """Produce a :class:`SchemaDocument` for this DB source.

        SQL dialects (postgresql / mysql / mssql) delegate to
        :class:`SqlDatabaseConnector`; MongoDB delegates to
        :class:`~src.connectors.mongodb_connector.MongoDBConnector` (schema-
        on-read). The delegate raises :class:`SchemaStudyPhaseError` on a
        fatal phase failure so the orchestrator stamps the right state.
        """
        study_schema = getattr(self._delegate, "study_schema", None)
        if study_schema is None:
            raise NotImplementedError(
                f"{type(self._delegate).__name__} does not implement study_schema()"
            )
        return await study_schema()


class SqlDatabaseConnector(BaseConnector):
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

    # Map ``config["db_type"]`` values to sqlglot dialect names. ``"mssql"``
    # is sqlglot's ``"tsql"``. Anything else (or missing) falls back to
    # ``"postgres"`` — the safest default for this project.
    _DIALECT_BY_DB_TYPE: dict[str, str] = {
        "postgresql": "postgres",
        "mysql": "mysql",
        "mssql": "tsql",
    }

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        # Hash the connection string immediately — never store it plain
        self._conn_str_hash: str = hashlib.sha256(
            config["connection_string"].encode()
        ).hexdigest()[:12]
        self._dialect: str = self._DIALECT_BY_DB_TYPE.get(
            str(config.get("db_type", "")), "postgres"
        )
        self._validate_query(config["query"])
        self._query: str = config["query"]
        self._page_size: int = int(config.get("page_size", 1000))
        self._source_id: str | None = config.get("source_id")
        self._engine: Any | None = None

    def _validate_query(self, query: str) -> None:
        """Allow only a single SELECT statement.

        Delegates to the shared :func:`validate_sql` validator (sqlglot AST
        based) so this connector and the text-to-query agent node enforce
        identical rules. Raises :class:`ValueError` to preserve the
        existing exception contract callers depend on.
        """
        result = validate_sql(query, dialect=self._dialect)
        if not result.is_safe:
            # ``reason`` never embeds the query text (FR-020).
            raise ValueError(result.reason or "SQL validation failed.")

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def _build_hardened_engine(
        self, *, pool_size: int, pool_pre_ping: bool
    ) -> Any:
        """Build an async engine with per-dialect read-only hardening applied.

        * **postgresql** — connection-string augmentation
          (``default_transaction_read_only=on`` + ``statement_timeout``).
        * **mysql** — a ``connect`` event handler issues ``SET SESSION
          TRANSACTION READ ONLY`` + server-side timeouts on every connection.
        * **mssql** — ``connect_args`` carry the driver command timeout and a
          ``connect`` handler issues ``SET LOCK_TIMEOUT`` + ``READ
          UNCOMMITTED`` isolation (lock-avoidance — SQL Server has no
          per-session read-only switch; enforcement is the SELECT-only gate +
          read-only-by-nature reflection).
        """
        from src.services.db_safety import (  # noqa: PLC0415
            harden_connection,
            harden_postgres_engine_kwargs,
            mssql_connect_args,
        )

        conn_str: str = self._config["connection_string"]
        db_type = self._config.get("db_type")
        connect_args: dict[str, Any] = {}
        if db_type == "postgresql" or (
            db_type is None and conn_str.startswith(("postgresql", "postgres"))
        ):
            try:
                hardened = await harden_postgres_engine_kwargs(conn_str)
                conn_str = hardened.url
                connect_args = hardened.connect_args
            except ValueError:
                # On rejection, build with the raw conn_str + empty
                # connect_args — the connect probe still protects us and we
                # don't widen the blast radius.
                logger.warning(
                    "DatabaseConnector: postgres hardening rejected URL "
                    "[conn_hash=%s] — falling back to raw conn_str",
                    self._conn_str_hash,
                )
        elif db_type == "mssql":
            connect_args = mssql_connect_args()

        engine = create_async_engine(
            conn_str,
            pool_pre_ping=pool_pre_ping,
            pool_size=pool_size,
            max_overflow=0,
            connect_args=connect_args,
        )
        if db_type in ("mysql", "mssql"):
            try:
                harden_connection(engine, dialect=db_type)  # type: ignore[arg-type]
            except Exception:  # noqa: BLE001 - best-effort, never fatal
                logger.warning(
                    "DatabaseConnector: %s hardening could not be wired "
                    "[conn_hash=%s] — continuing",
                    db_type,
                    self._conn_str_hash,
                )
        return engine

    async def connect(self) -> None:
        """
        Create an async SQLAlchemy engine and perform a connectivity check.
        Raises ConnectionError (not the raw driver exception, which may contain
        the connection string in its message) if the test SELECT 1 fails.

        The engine is read-only-hardened per dialect — see
        :meth:`_build_hardened_engine`.
        """
        try:
            engine = await self._build_hardened_engine(
                pool_size=2, pool_pre_ping=True
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
        Execute SELECT 1 via a temporary read-only-hardened engine.
        Returns False (not raises) on any failure.
        connection_string MUST NOT appear in any log or exception message.

        The probe uses the same per-dialect hardening as ``connect()``
        (:meth:`_build_hardened_engine`) so even the connectivity check
        cannot mutate the source database (Postgres: libpq read-only +
        statement_timeout; MySQL: ``SET SESSION TRANSACTION READ ONLY`` +
        timeouts; MSSQL: lock-timeout + READ UNCOMMITTED — see that method).
        """
        try:
            engine = await self._build_hardened_engine(
                pool_size=1, pool_pre_ping=False
            )
            async with engine.connect() as conn:
                await conn.execute(sa.text("SELECT 1"))
            await engine.dispose()
            return True
        except Exception as exc:
            # Log the exception class + message + traceback so operators can
            # debug a failed admin "Test connection". The connection string
            # is NEVER part of `str(exc)` for asyncpg/SQLAlchemy errors —
            # those drivers report field-level details (host, user, dbname)
            # but not the URI verbatim. The caller still gets a sanitised
            # ConnectionError (see source_inspection_service.inspect_source).
            logger.warning(
                "DatabaseConnector.test_connection failed [conn_hash=%s]: %s: %s",
                self._conn_str_hash,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return False

    # ------------------------------------------------------------------ #
    # Schema study (studying-agent)
    # ------------------------------------------------------------------ #

    async def study_schema(self) -> SchemaDocument:
        """Run the studying-agent's 6-phase introspection for this source.

        Delegates to :func:`src.services.db_introspection.sql_inspector.study_sql_schema`,
        which opens its own read-only-hardened engine, reflects the schema,
        samples (PII-redacted), and asks the ``schema_inspector`` LLM stage
        for table descriptions + a corpus summary.

        The connector's own ``_engine`` (used for document extraction) is
        intentionally NOT reused — the inspector wants a fresh hardened
        engine and disposes it itself.

        Raises:
            SchemaStudyPhaseError: on a fatal phase failure (the orchestrator
                derives the failed state from ``.phase``).
        """
        from src.services.db_introspection.sql_inspector import (  # noqa: PLC0415
            study_sql_schema,
        )

        db_type = str(self._config.get("db_type") or "postgresql")
        resolver = self._resolve_ai_model_resolver()
        return await study_sql_schema(
            connection_string=self._config["connection_string"],
            db_type=db_type,
            ai_model_resolver=resolver,
        )

    @staticmethod
    def _resolve_ai_model_resolver() -> Any:
        """Best-effort fetch of the singleton :class:`AIModelResolver`.

        Returns ``None`` if the DI container can't be constructed (e.g. in a
        stripped-down test context) — the inspector then skips the
        DESCRIBING phase and marks the study partial rather than failing.
        """
        try:
            from src.core.container import Container  # noqa: PLC0415

            return Container.ai_model_resolver()
        except Exception:  # noqa: BLE001 - degrade gracefully
            logger.warning(
                "SqlDatabaseConnector: AIModelResolver unavailable — "
                "DESCRIBING phase will be skipped"
            )
            return None
