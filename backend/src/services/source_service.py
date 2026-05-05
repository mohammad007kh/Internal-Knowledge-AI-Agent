"""Source service — business-logic layer for Source management.

Implements T-042.

Design decisions
----------------
- Fernet symmetric encryption is used for ``config_encrypted`` (FR-020).
- The raw config dict is never exposed through API responses;
  ``get_source_config()`` is for internal / connector use only.
- ``test_connection()`` defers to the connector registry (a later task) and
  always returns ``False`` on any error so callers are unconditionally safe.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, cast
from urllib.parse import quote_plus

from cryptography.fernet import Fernet
from pydantic import ValidationError

from src.connectors.factory import ConnectorFactory
from src.core.config import Settings
from src.core.exceptions import ConflictError, NotFoundError
from src.models.enums import SourceType
from src.models.source import Source
from src.repositories.source_repository import SourceRepository
from src.schemas.source import (
    FILE_SOURCE_TYPES,
    DatabaseConnectionConfig,
    SourceCreate,
    SourceCreateRequest,
    SourceUpdate,
)

logger = logging.getLogger(__name__)

# SQLAlchemy async-driver mapping per SQL dialect.
_SQL_DIALECT_DRIVERS: dict[str, str] = {
    "postgresql": "postgresql+asyncpg",
    "mysql": "mysql+aiomysql",
    "mssql": "mssql+aioodbc",
}


class SourceService:
    """Business-logic layer for Source CRUD and config encryption."""

    def __init__(
        self,
        source_repo: SourceRepository,
        settings: Settings,
        connector_factory: ConnectorFactory,
    ) -> None:
        self._repo = source_repo
        self._settings = settings
        self._fernet = Fernet(settings.ENCRYPTION_KEY.encode())
        self._connector_factory = connector_factory

    # ------------------------------------------------------------------ #
    # Encryption helpers
    # ------------------------------------------------------------------ #

    def _encrypt_config(self, config: dict[str, Any]) -> bytes:
        """Serialise *config* to JSON and Fernet-encrypt the bytes."""
        return self._fernet.encrypt(json.dumps(config).encode())

    def _decrypt_config(self, data: bytes) -> dict[str, Any]:
        """Fernet-decrypt *data* and deserialise from JSON."""
        decrypted: str = self._fernet.decrypt(data).decode()
        return cast("dict[str, Any]", json.loads(decrypted))

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #

    async def create_source(
        self,
        payload: SourceCreate,
        owner_id: uuid.UUID,
    ) -> Source:
        """Create a new Source for *owner_id*.

        Raises:
            ConflictError: if a source named *payload.name* already belongs
                to this owner.
        """
        existing = await self._repo.find_by_name_and_owner(payload.name, owner_id)
        if existing is not None:
            raise ConflictError(
                f"A source named {payload.name!r} already exists for this user."
            )
        config_encrypted = self._encrypt_config(payload.config)
        return await self._repo.create(
            name=payload.name,
            source_type=payload.source_type,
            config_encrypted=config_encrypted,
            owner_id=owner_id,
        )

    async def create_source_v2(
        self,
        payload: SourceCreateRequest,
        owner_id: uuid.UUID,
    ) -> Source:
        """Create a Source from the wizard's structured request (T-004).

        For file-typed sources the persisted ``source_type`` is normalised to
        the canonical :pyattr:`SourceType.FILE_UPLOAD` enum value.  The list of
        uploaded files (object_key + file_type + original_name) is encrypted
        into ``config_encrypted`` so the connector can iterate through them at
        sync time.

        Raises:
            ConflictError: if a source with the same name exists for this owner.
        """
        existing = await self._repo.find_by_name_and_owner(payload.name, owner_id)
        if existing is not None:
            raise ConflictError(
                f"A source named {payload.name!r} already exists for this user."
            )

        is_file = payload.source_type in FILE_SOURCE_TYPES
        is_database = payload.source_type == "database"
        source_mode = "snapshot" if is_file else "live"

        # Determine the persisted source_type and config payload.
        persisted_source_type: str
        config_for_encryption: dict[str, Any] | None
        first_object_key: str | None = None

        if is_file:
            # Always persist the canonical enum value — the granular
            # 'pdf'/'docx'/... shorthands are NOT valid SourceType members.
            persisted_source_type = SourceType.FILE_UPLOAD.value

            files_payload = self._normalise_file_refs(payload)
            first_object_key = files_payload[0]["object_key"] if files_payload else None

            config_for_encryption = {
                "minio_bucket": self._settings.MINIO_BUCKET,
                "files": files_payload,
            }
        elif is_database:
            # Translate the typed wizard payload into the connector-shaped
            # config that ``DatabaseConnector`` / ``MongoDBConnector`` expect.
            persisted_source_type = SourceType.DATABASE.value
            try:
                typed_conn = DatabaseConnectionConfig.model_validate(
                    payload.connection or {}
                )
            except ValidationError as exc:
                # Surface the underlying field issues to the caller.
                raise ValueError(
                    f"Invalid database connection payload: {exc.errors()}"
                ) from exc
            config_for_encryption = self._build_database_config(typed_conn)
        else:
            persisted_source_type = payload.source_type
            config_for_encryption = payload.connection

        config_encrypted: bytes | None = (
            self._encrypt_config(config_for_encryption) if config_for_encryption else None
        )

        return await self._repo.create(
            name=payload.name,
            source_type=persisted_source_type,
            source_mode=source_mode,
            retrieval_mode=payload.retrieval_mode,
            description=payload.description or None,
            sync_mode=payload.sync_mode,
            sync_schedule=payload.sync_schedule,
            citations_enabled=payload.citations_enabled,
            config_encrypted=config_encrypted,
            file_storage_path=first_object_key,
            owner_id=owner_id,
            status="pending",
        )

    @staticmethod
    def _build_database_config(typed: DatabaseConnectionConfig) -> dict[str, Any]:
        """Translate the wizard's typed DB payload into the connector-shaped config.

        Returns the dict that will be Fernet-encrypted into ``config_encrypted``
        and later read by the connector at sync time.

        Output shapes:
          * SQL dialects (postgresql/mysql/mssql)::
              {
                  "db_type": <dialect>,
                  "connection_string": "<scheme>://user:pwd@host:port/db",
                  "query": <SELECT statement>,
                  "ssl_mode": <"disable"|"require"|None>,
              }
          * MongoDB::
              {
                  "db_type": "mongodb",
                  "uri": "mongodb://user:pwd@host:port",
                  "database": <db>,
                  "collection": <collection>,
              }

        Empty username AND password are omitted from the URL (anonymous
        connection) instead of producing ``://:@host``.  Both username and
        password are URL-quoted via :func:`urllib.parse.quote_plus`.
        """
        user = typed.username.strip() if typed.username else ""
        pw = typed.password if typed.password else ""
        if user or pw:
            auth = f"{quote_plus(user)}:{quote_plus(pw)}@"
        else:
            auth = ""

        if typed.db_type == "mongodb":
            uri = f"mongodb://{auth}{typed.host}:{typed.port}"
            return {
                "db_type": "mongodb",
                "uri": uri,
                "database": typed.database,
                "collection": (typed.collection or "").strip(),
            }

        # SQL dialects.
        scheme = _SQL_DIALECT_DRIVERS.get(typed.db_type)
        if scheme is None:  # pragma: no cover — guarded by Pydantic literal
            raise ValueError(f"Unsupported SQL dialect: {typed.db_type!r}")

        if typed.db_type == "mssql":
            # The aioodbc driver may not be installed in this environment.
            # We still build the URL so creation succeeds; sync will fail
            # later with a clear error message — log a warning here to make
            # that visible in operations dashboards.
            logger.warning(
                "Creating MSSQL source: ensure 'aioodbc' driver is installed "
                "for sync to succeed."
            )

        connection_string = (
            f"{scheme}://{auth}{typed.host}:{typed.port}/{typed.database}"
        )
        cfg: dict[str, Any] = {
            "db_type": typed.db_type,
            "connection_string": connection_string,
            "query": (typed.query or "").strip(),
        }
        if typed.ssl_mode is not None:
            cfg["ssl_mode"] = typed.ssl_mode
        return cfg

    @staticmethod
    def _normalise_file_refs(payload: SourceCreateRequest) -> list[dict[str, Any]]:
        """Return the list of files for a file-typed source.

        Prefers ``payload.files`` (multi-file shape).  Falls back to the legacy
        single ``object_key`` + scalar ``source_type`` pair when ``files`` is
        absent — converting it into a single-element list.
        """
        if payload.files:
            return [
                {
                    "object_key": ref.object_key,
                    "original_name": ref.original_name,
                    "file_type": ref.file_type,
                    "size_bytes": ref.size_bytes,
                }
                for ref in payload.files
            ]
        if payload.object_key:
            # Legacy: source_type was a per-extension shorthand.  Map "markdown"
            # to its alias understood by the connector ("md") downstream.
            return [
                {
                    "object_key": payload.object_key,
                    "original_name": payload.object_key.rsplit("/", 1)[-1],
                    "file_type": payload.source_type,
                    "size_bytes": None,
                }
            ]
        return []

    async def get_source(self, source_id: uuid.UUID) -> Source:
        """Fetch a single Source by PK.

        Raises:
            NotFoundError: if no active Source exists for *source_id*.
        """
        source = await self._repo.get_by_id(source_id)
        if source is None:
            raise NotFoundError(f"Source {source_id} not found.")
        return source

    async def update_source(
        self,
        source_id: uuid.UUID,
        payload: SourceUpdate,
    ) -> Source:
        """Partially update a Source.

        Only non-``None`` payload fields are written.  If *config* is
        supplied it is re-encrypted before storage.

        Raises:
            NotFoundError: if *source_id* does not match an active Source.
        """
        # Verify existence before building kwargs.
        await self.get_source(source_id)

        kwargs: dict[str, Any] = {}
        if payload.name is not None:
            kwargs["name"] = payload.name
        if payload.is_active is not None:
            kwargs["is_active"] = payload.is_active
        if payload.config is not None:
            kwargs["config_encrypted"] = self._encrypt_config(payload.config)

        # No-op: re-fetch and return existing object unchanged.
        if not kwargs:
            return await self.get_source(source_id)

        updated = await self._repo.update(source_id, **kwargs)
        if updated is None:
            raise NotFoundError(f"Source {source_id} not found.")
        return updated

    async def delete_source(self, source_id: uuid.UUID) -> None:
        """Soft-delete a Source (sets ``deleted_at = now()``).

        Approval state (``is_active``) is preserved unchanged so the audit
        trail can show whether the source was approved at the time of
        deletion.

        Raises:
            NotFoundError: if *source_id* is not found or already
            soft-deleted.
        """
        deleted = await self._repo.soft_delete(source_id)
        if not deleted:
            raise NotFoundError(
                f"Source {source_id} not found or already deleted."
            )

    # ------------------------------------------------------------------ #
    # Config access — INTERNAL ONLY, never surfaced via API (FR-020)
    # ------------------------------------------------------------------ #

    async def get_source_config(self, source_id: uuid.UUID) -> dict[str, Any]:
        """Return the decrypted connection config for *source_id*.

        **Internal use only** — never expose the return value in API responses.

        Raises:
            NotFoundError: if *source_id* does not match an active Source.
        """
        source = await self.get_source(source_id)
        if source.config_encrypted is None:
            return {}
        return self._decrypt_config(source.config_encrypted)

    # ------------------------------------------------------------------ #
    # List helpers
    # ------------------------------------------------------------------ #

    async def list_sources_for_owner(
        self,
        owner_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
        available_only: bool = False,
    ) -> tuple[list[Source], int]:
        """Return paginated non-deleted sources for *owner_id* with a total count.

        ``available_only=True`` restricts to admin-approved
        (``is_active = TRUE``) — pass this from user-facing surfaces such as
        the chat session source picker.
        """
        sources = await self._repo.list_by_owner_with_jobs(
            owner_id, skip=skip, limit=limit, available_only=available_only
        )
        total = await self._repo.count_by_owner(
            owner_id, available_only=available_only
        )
        return sources, total

    async def list_all_active_sources(
        self,
        skip: int = 0,
        limit: int = 100,
        available_only: bool = False,
    ) -> tuple[list[Source], int]:
        """Return all non-deleted sources (admin view) with a total count.

        ``available_only=True`` restricts to admin-approved sources — pass
        this when the consumer is the chat session source picker.
        """
        sources = await self._repo.list_active_with_jobs(
            skip=skip, limit=limit, available_only=available_only
        )
        total = await self._repo.count_active(available_only=available_only)
        return sources, total

    # ------------------------------------------------------------------ #
    # Aggregate listings (T-107 ingestion-clarity)
    # ------------------------------------------------------------------ #

    async def list_sources_for_owner_with_counts(
        self,
        owner_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        available_only: bool = False,
    ) -> tuple[list[tuple[Source, int, int]], int]:
        """Owner-scoped listing with per-source document/chunk counts.

        Single round-trip — counts are computed via correlated subqueries
        in the repository so the result stays bounded by ``limit`` rather
        than the full sources table.
        """
        return await self._repo.list_with_counts(
            owner_id=owner_id,
            skip=skip,
            limit=limit,
            available_only=available_only,
        )

    async def list_all_sources_with_counts(
        self,
        *,
        skip: int = 0,
        limit: int = 100,
        available_only: bool = False,
    ) -> tuple[list[tuple[Source, int, int]], int]:
        """Admin listing with per-source document/chunk counts.

        Mirrors :meth:`list_all_active_sources` but adds aggregate counts
        for the four-stage ingestion-clarity strip on the admin sources
        table — without an N+1.
        """
        return await self._repo.list_with_counts(
            owner_id=None,
            skip=skip,
            limit=limit,
            available_only=available_only,
        )

    # ------------------------------------------------------------------ #
    # Connectivity test
    # ------------------------------------------------------------------ #

    async def test_connection(self, source_id: uuid.UUID) -> bool:
        """Probe the connector for *source_id*; always returns ``False`` on error.

        The connector registry import is deferred so this method is safe to
        call before the connector subsystem is fully wired up.
        """
        try:
            source = await self.get_source(source_id)
            config = await self.get_source_config(source_id)
            connector = self._connector_factory.build(
                source_type=source.source_type,
                source_id=str(source_id),
                decrypted_config=config,
            )
            return bool(await connector.test_connection())
        except Exception:  # noqa: BLE001
            return False
