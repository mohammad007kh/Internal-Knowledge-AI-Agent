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
import uuid
from typing import Any, cast

from cryptography.fernet import Fernet

from src.connectors.factory import ConnectorFactory
from src.core.config import Settings
from src.core.exceptions import ConflictError, NotFoundError
from src.models.source import Source
from src.repositories.source_repository import SourceRepository
from src.schemas.source import SourceCreate, SourceUpdate


class SourceService:
    """Business-logic layer for Source CRUD and config encryption."""

    def __init__(
        self,
        source_repo: SourceRepository,
        settings: Settings,
        connector_factory: ConnectorFactory,
    ) -> None:
        self._repo = source_repo
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
        """Soft-delete a Source (sets ``is_active = False``).

        Raises:
            NotFoundError: if *source_id* is not found or already inactive.
        """
        deactivated = await self._repo.deactivate(source_id)
        if not deactivated:
            raise NotFoundError(
                f"Source {source_id} not found or already inactive."
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
    ) -> tuple[list[Source], int]:
        """Return paginated sources for *owner_id* with a total count."""
        sources = await self._repo.list_by_owner_with_jobs(owner_id, skip=skip, limit=limit)
        total = await self._repo.count_by_owner(owner_id)
        return sources, total

    async def list_all_active_sources(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Source], int]:
        """Return all active sources (admin view) with a total count."""
        sources = await self._repo.list_active_with_jobs(skip=skip, limit=limit)
        total = await self._repo.count_active()
        return sources, total

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
