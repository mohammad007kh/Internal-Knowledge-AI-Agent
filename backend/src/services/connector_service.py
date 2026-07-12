"""Connector service — business-logic layer for Connector management.

Mirrors the encryption pattern used by SourceService (FR-020 equivalent).
The raw config dict is never exposed through API responses.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from cryptography.fernet import Fernet

from src.connectors.registry import get_connector
from src.core.config import Settings
from src.core.exceptions import NotFoundError
from src.models.connector import Connector
from src.repositories.connector_repository import ConnectorRepository
from src.schemas.connector import ConnectorCreate, ConnectorUpdate


class ConnectorService:
    """Business-logic layer for Connector CRUD and config encryption."""

    def __init__(
        self,
        repo: ConnectorRepository,
        settings: Settings,
    ) -> None:
        self._repo = repo
        self._fernet = Fernet(settings.ENCRYPTION_KEY.encode())

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

    async def list_connectors(
        self,
        owner_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
        *,
        admin: bool = False,
    ) -> tuple[list[Connector], int]:
        """Return paginated connectors.

        Admins see all connectors; regular users see only their own.
        """
        if admin:
            items = await self._repo.list_all(skip=skip, limit=limit)
            total = await self._repo.count_all()
        else:
            items = await self._repo.list_by_owner(owner_id, skip=skip, limit=limit)
            total = await self._repo.count_by_owner(owner_id)
        return items, total

    async def get_connector(self, connector_id: uuid.UUID) -> Connector:
        """Fetch a single Connector by PK.

        Raises:
            NotFoundError: if no Connector exists for *connector_id*.
        """
        connector = await self._repo.get(connector_id)
        if connector is None:
            raise NotFoundError(f"Connector {connector_id} not found.")
        return connector

    async def create_connector(
        self,
        payload: ConnectorCreate,
        owner_id: uuid.UUID,
    ) -> Connector:
        """Create a new Connector for *owner_id*.

        Encrypts config if provided.
        """
        config_encrypted: bytes | None = None
        if payload.config is not None:
            config_encrypted = self._encrypt_config(payload.config)

        return await self._repo.create(
            name=payload.name,
            connector_type=payload.connector_type,
            config_encrypted=config_encrypted,
            owner_id=owner_id,
        )

    async def update_connector(
        self,
        connector_id: uuid.UUID,
        payload: ConnectorUpdate,
        owner_id: uuid.UUID,
    ) -> Connector:
        """Partially update a Connector.

        Raises:
            NotFoundError: if *connector_id* does not match a Connector.
        """
        await self.get_connector(connector_id)

        kwargs: dict[str, Any] = {}
        if payload.name is not None:
            kwargs["name"] = payload.name
        if payload.is_active is not None:
            kwargs["is_active"] = payload.is_active
        if payload.config is not None:
            kwargs["config_encrypted"] = self._encrypt_config(payload.config)

        if not kwargs:
            return await self.get_connector(connector_id)

        updated = await self._repo.update(connector_id, **kwargs)
        if updated is None:
            raise NotFoundError(f"Connector {connector_id} not found.")
        return updated

    async def delete_connector(
        self,
        connector_id: uuid.UUID,
        owner_id: uuid.UUID,
    ) -> None:
        """Hard-delete a Connector.

        Raises:
            NotFoundError: if *connector_id* is not found.
        """
        deleted = await self._repo.delete(connector_id)
        if not deleted:
            raise NotFoundError(f"Connector {connector_id} not found.")

    async def test_connection(
        self,
        connector_id: uuid.UUID,
        owner_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Test connectivity for the given connector.

        Decrypts config, delegates to the connector registry.
        Always returns ``{"success": bool, "message": str}``.
        """
        try:
            connector = await self.get_connector(connector_id)
            config: dict[str, Any] = {}
            if connector.config_encrypted is not None:
                config = self._decrypt_config(connector.config_encrypted)
            instance = get_connector(connector.connector_type, config)
            ok = bool(await instance.test_connection())

            # Update last_tested_at
            await self._repo.update(connector_id, last_tested_at=datetime.now(UTC))

            return {"success": ok, "message": "" if ok else "Connection attempt failed."}
        except NotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Returned verbatim to the API client. A connector build /
            # config-decrypt failure could embed a DSN fragment in
            # ``str(exc)``; scrub it before it leaves the boundary (FR-020).
            from src.connectors.database_connector import (  # noqa: PLC0415
                _sanitise as _sanitise_dsn,
            )

            return {"success": False, "message": _sanitise_dsn(exc)}
