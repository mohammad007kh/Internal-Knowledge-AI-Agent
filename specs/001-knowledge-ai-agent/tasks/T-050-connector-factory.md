# T-050 — ConnectorFactory (DI-wired)

## Context
```
Python 3.12 | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector
PostgreSQL 16 + pgvector · Celery + Redis · MinIO
JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC
Fernet (connection configs at rest)
RFC 7807 Problem Details — all non-2xx API responses
Docker Compose 9 services
```

## Goal
Introduce a `ConnectorFactory` class that wraps the bare `get_connector()` function,
wires it into the dependency-injector DI container as a `Singleton`, and updates
`SourceService` to use it instead of calling `get_connector` directly.

This isolates connector instantiation behind a seam that can be mocked in tests.

---

## File 1 — `app/connectors/factory.py`

```python
"""Factory for instantiating connectors through the DI container."""
from __future__ import annotations

import logging
from typing import Any

from app.connectors.base import BaseConnector
from app.connectors.registry import get_connector
from app.models.enums import SourceType

logger = logging.getLogger(__name__)


class ConnectorFactory:
    """
    Thin wrapper around get_connector() that:
    - Centralises connector instantiation.
    - Logs source_id + source_type for observability WITHOUT exposing config.
    - Provides a single mock target for unit tests (mock ConnectorFactory.build
      instead of patching the module-level get_connector function).
    """

    def build(
        self,
        source_type: SourceType,
        source_id: str,
        decrypted_config: dict[str, Any],
    ) -> BaseConnector:
        """
        Instantiate and return a connector for the given source_type.

        Args:
            source_type:      The SourceType enum value.
            source_id:        UUID string of the Source (for logging only).
            decrypted_config: Plaintext config dict — NEVER logged or re-raised
                              in exception messages (FR-020).

        Returns:
            A concrete BaseConnector instance.

        Raises:
            ValueError: if source_type is not registered in CONNECTOR_REGISTRY.
        """
        logger.info(
            "ConnectorFactory.build",
            extra={"source_id": source_id, "source_type": source_type.value},
        )
        # get_connector raises ValueError for unregistered types — let it propagate.
        return get_connector(source_type, decrypted_config)
```

---

## File 2 — `app/containers.py` (patch)

Add `connector_factory` singleton to the existing `DeclarativeContainer`:

```python
# Inside class ApplicationContainer(DeclarativeContainer):

    connector_factory = providers.Singleton(
        ConnectorFactory,
    )
```

Full diff context (add after `storage_service` declaration):

```python
# --- existing ---
storage_service = providers.Singleton(
    StorageService,
    config=config,
)

# --- add ---
connector_factory = providers.Singleton(
    ConnectorFactory,
)
```

Import at top of `app/containers.py`:

```python
from app.connectors.factory import ConnectorFactory
```

---

## File 3 — `app/services/source_service.py` (patch)

Replace the direct `get_connector()` call in `test_connection()` with
`ConnectorFactory.build()`.

### Constructor change

```python
# BEFORE
def __init__(
    self,
    source_repo: SourceRepository,
    fernet: Fernet,
) -> None:
    self._repo = source_repo
    self._fernet = fernet

# AFTER
def __init__(
    self,
    source_repo: SourceRepository,
    fernet: Fernet,
    connector_factory: ConnectorFactory,
) -> None:
    self._repo = source_repo
    self._fernet = fernet
    self._connector_factory = connector_factory
```

### `test_connection` change

```python
# BEFORE (T-042)
async def test_connection(self, source_id: UUID) -> bool:
    source = await self.get_source(source_id)
    decrypted = self._decrypt_config(source.config_encrypted)
    try:
        connector = get_connector(source.source_type, decrypted)
        async with connector:
            return await connector.test_connection()
    except Exception:
        logger.exception(
            "test_connection failed",
            extra={"source_id": str(source_id), "source_type": source.source_type.value},
        )
        return False

# AFTER — use factory; remove get_connector import
async def test_connection(self, source_id: UUID) -> bool:
    source = await self.get_source(source_id)
    decrypted = self._decrypt_config(source.config_encrypted)
    try:
        connector = self._connector_factory.build(
            source_type=source.source_type,
            source_id=str(source_id),
            decrypted_config=decrypted,
        )
        async with connector:
            return await connector.test_connection()
    except Exception:
        logger.exception(
            "test_connection failed",
            extra={"source_id": str(source_id), "source_type": source.source_type.value},
        )
        return False
```

Remove the `get_connector` import line from `source_service.py`.

---

## File 4 — `app/api/v1/sources.py` (patch)

Update the DI `Depends` for the sources router so it receives `connector_factory`
from the container:

```python
# The router already injects source_service via Depends.
# source_service itself now requires connector_factory, which the DI container
# resolves automatically — no change needed in the router if source_service is
# injected as a Factory provider that wires its own dependencies.

# Verify app/containers.py wires source_service with connector_factory:

source_service = providers.Factory(
    SourceService,
    source_repo=source_repository,
    fernet=fernet,
    connector_factory=connector_factory,   # <-- add this line
)
```

---

## Acceptance Criteria

1. `ConnectorFactory` is importable from `app.connectors.factory`.
2. `ConnectorFactory.build(SourceType.WEB_URL, "some-id", {"url": "https://x.com"})`
   returns a `WebUrlConnector` instance.
3. `ConnectorFactory.build(SourceType.DATABASE, "some-id", {})` raises `ValueError`
   only when the type is unregistered — for a registered type it returns the connector.
4. `ApplicationContainer.connector_factory()` returns a `ConnectorFactory` singleton.
5. `SourceService` no longer imports `get_connector` directly.
6. `SourceService.test_connection()` delegates to `self._connector_factory.build()`.
7. Unit test for `test_connection()` can mock `ConnectorFactory.build` without patching
   `app.connectors.registry.get_connector`.
8. `source_ip.py` (or equivalent DI wiring) passes `connector_factory` to
   `SourceService` as a constructor argument.
9. No connector config values appear in any log line emitted by `ConnectorFactory`.
