# T-042 â€” Source Service

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x async Â· dependency-injector
Fernet symmetric encryption Â· pydantic_settings Â· RFC 7807 errors
```

## Goal
Implement `SourceService` â€” the business-logic layer for source management. Handles Fernet encrypt/decrypt of connection configs and CRUD orchestration. Connection configs must **never** appear in API responses (FR-020).

---

## File â€” `app/services/source_service.py`

```python
from __future__ import annotations

import json
import uuid
from typing import Any

from cryptography.fernet import Fernet

from app.core.errors import ConflictError, NotFoundError
from app.core.settings import Settings
from app.models.enums import SourceType
from app.models.source import Source
from app.repositories.source_repository import SourceRepository
from app.schemas.source import SourceCreate, SourceUpdate


class SourceService:
    """Business-logic layer for Source management."""

    def __init__(
        self,
        source_repo: SourceRepository,
        settings: Settings,
    ) -> None:
        self._repo = source_repo
        self._fernet = Fernet(settings.fernet_key.encode())

    # ------------------------------------------------------------------ #
    # Encryption helpers â€” PRIVATE, never exposed via API
    # ------------------------------------------------------------------ #

    def _encrypt_config(self, config: dict[str, Any]) -> bytes:
        """Serialize config dict to JSON and Fernet-encrypt it."""
        raw = json.dumps(config, separators=(",", ":")).encode()
        return self._fernet.encrypt(raw)

    def _decrypt_config(self, data: bytes) -> dict[str, Any]:
        """Fernet-decrypt and deserialize config bytes back to dict."""
        raw = self._fernet.decrypt(data)
        return json.loads(raw.decode())

    # ------------------------------------------------------------------ #
    # Public CRUD
    # ------------------------------------------------------------------ #

    async def create_source(
        self,
        payload: SourceCreate,
        owner_id: uuid.UUID,
    ) -> Source:
        """
        Create a new source.
        Raises ConflictError if the owner already has a source with the same name.
        """
        existing = await self._repo.find_by_name_and_owner(payload.name, owner_id)
        if existing:
            raise ConflictError(
                detail=f"A source named '{payload.name}' already exists for this user.",
                pointer="/name",
            )

        encrypted = self._encrypt_config(payload.config)

        source = Source(
            name=payload.name,
            source_type=payload.source_type,
            config_encrypted=encrypted,
            owner_id=owner_id,
            is_active=True,
        )
        return await self._repo.save(source)

    async def get_source(self, source_id: uuid.UUID) -> Source:
        """
        Return a source by PK.
        Raises NotFoundError when missing.
        """
        source = await self._repo.get_by_id(source_id)
        if not source:
            raise NotFoundError(detail=f"Source '{source_id}' not found.")
        return source

    async def update_source(
        self,
        source_id: uuid.UUID,
        payload: SourceUpdate,
    ) -> Source:
        """
        Partial update.  Only provided fields are changed.
        Re-encrypts config if a new config dict is supplied.
        """
        source = await self.get_source(source_id)

        if payload.name is not None:
            # Check duplicate name under the same owner
            conflict = await self._repo.find_by_name_and_owner(
                payload.name, source.owner_id
            )
            if conflict and conflict.id != source_id:
                raise ConflictError(
                    detail=f"A source named '{payload.name}' already exists for this user.",
                    pointer="/name",
                )
            source.name = payload.name

        if payload.config is not None:
            source.config_encrypted = self._encrypt_config(payload.config)

        if payload.is_active is not None:
            source.is_active = payload.is_active

        return await self._repo.save(source)

    async def delete_source(self, source_id: uuid.UUID) -> None:
        """
        Soft-delete a source (sets is_active=False).
        Raises NotFoundError if already gone.
        """
        deactivated = await self._repo.deactivate(source_id)
        if not deactivated:
            raise NotFoundError(detail=f"Source '{source_id}' not found.")

    # ------------------------------------------------------------------ #
    # Config access â€” only for internal services, NEVER for API responses
    # ------------------------------------------------------------------ #

    async def get_source_config(self, source_id: uuid.UUID) -> dict[str, Any]:
        """
        Decrypt and return the connection config for internal use.
        MUST NOT be called from any HTTP handler â€” use connector/sync services only.
        """
        source = await self.get_source(source_id)
        return self._decrypt_config(source.config_encrypted)

    # ------------------------------------------------------------------ #
    # Listing
    # ------------------------------------------------------------------ #

    async def list_sources_for_owner(
        self,
        owner_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Source], int]:
        """Return (sources, total_count) for a given owner."""
        sources = await self._repo.list_by_owner(owner_id, skip=skip, limit=limit)
        total = await self._repo.count_by_owner(owner_id)
        return sources, total

    async def list_all_active_sources(
        self,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Source], int]:
        """Admin view: return all active sources with count."""
        sources = await self._repo.list_active(skip=skip, limit=limit)
        total = await self._repo.count_active()
        return sources, total

    async def test_connection(self, source_id: uuid.UUID) -> bool:
        """
        Decrypt config and invoke the connector's test_connection.
        Returns True on success; False on any connector error.
        Always catches exceptions â€” never exposes raw error to API layer.
        """
        import logging

        logger = logging.getLogger(__name__)

        try:
            from app.connectors.registry import get_connector

            source = await self.get_source(source_id)
            config = self._decrypt_config(source.config_encrypted)
            connector = get_connector(source.source_type, config)
            async with connector:
                return await connector.test_connection()
        except Exception:
            logger.exception("test_connection failed for source_id=%s", source_id)
            return False
```

---

## Domain Rules Enforced

| Rule | Enforcement |
|---|---|
| FR-020 â€” config never in API | `config_encrypted` stored only; `get_source_config()` is internal only |
| FR-019 â€” per-user isolation | `create_source` takes `owner_id` from JWT, not request body |
| Duplicate name guard | `ConflictError` raised before INSERT |
| Soft-delete | `deactivate()` â€” no hard DELETE |

---

## Error Classes (must already exist from T-016)

```python
# app/core/errors.py  (excerpt â€” verify before implementing)
class ConflictError(AppError):
    status_code: int = 409

class NotFoundError(AppError):
    status_code: int = 404
```

---

## Acceptance Criteria

- [ ] `SourceService` resolvable from DI container (wired in T-037 update)
- [ ] `create_source` raises `ConflictError` (409) on duplicate name per owner
- [ ] `update_source` with `config=None` does NOT re-encrypt (no change)
- [ ] `get_source_config` is not called by any router module
- [ ] `test_connection` returns `False` (not raises) on connector error
- [ ] Fernet round-trip: `_decrypt_config(_encrypt_config(d)) == d` for any valid dict
