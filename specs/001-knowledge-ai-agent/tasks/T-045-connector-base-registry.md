# T-045 — Connector Base + Registry

## Context
```
Python 3.12 | AsyncIterator · ABC · Pydantic v2
Connectors: WebUrl · FileUpload · Database · Confluence · SharePoint (SourceType enum)
```

## Goal
Define the shared `Document` value object, the `BaseConnector` abstract class, and the `CONNECTOR_REGISTRY` with its `@register` decorator and `get_connector` factory. All concrete connectors (T-046–T-049) will import from these modules.

---

## File 1 — `app/connectors/base.py`

```python
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field


# ------------------------------------------------------------------ #
# Document value object
# ------------------------------------------------------------------ #

class Document(BaseModel):
    """
    Unit of extracted content produced by a connector and passed downstream
    to the chunker → embedder → vector store pipeline.

    `raw_storage_path` is the MinIO object key where the raw file/page has been
    archived, or None if the connector streams inline text only.
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

    Concrete implementations MUST be registered via the `@register` decorator
    in `app/connectors/registry.py` before `get_connector` can return them.

    Usage (async context manager — preferred):
        async with get_connector(source_type, config) as conn:
            async for doc in conn.extract_documents():
                ...

    Usage (manual lifecycle):
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
        Raise `ConnectionError` (or a subclass) on failure.
        """

    @abstractmethod
    async def extract_documents(self) -> AsyncIterator[Document]:
        """
        Yield `Document` objects one at a time.
        Allows the pipeline to start processing before extraction completes.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Release all resources held by the connector.
        Must be idempotent — safe to call even if `connect` was never called.
        """

    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Attempt a lightweight connectivity check.
        Return True on success, False on any failure.
        MUST NOT raise — all exceptions must be caught internally.
        """

    # ---------------------------------------------------------------- #
    # Async context manager support
    # ---------------------------------------------------------------- #

    async def __aenter__(self) -> "BaseConnector":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.disconnect()
```

---

## File 2 — `app/connectors/registry.py`

```python
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.models.enums import SourceType

from .base import BaseConnector

# ------------------------------------------------------------------ #
# Registry
# ------------------------------------------------------------------ #

CONNECTOR_REGISTRY: dict[SourceType, type[BaseConnector]] = {}


def register(
    source_type: SourceType,
) -> Callable[[type[BaseConnector]], type[BaseConnector]]:
    """
    Class decorator that registers a concrete connector against a `SourceType`.

    Example::

        @register(SourceType.WEB_URL)
        class WebUrlConnector(BaseConnector):
            ...
    """

    def decorator(cls: type[BaseConnector]) -> type[BaseConnector]:
        if source_type in CONNECTOR_REGISTRY:
            raise RuntimeError(
                f"Connector for {source_type!r} is already registered "
                f"as {CONNECTOR_REGISTRY[source_type].__name__!r}."
            )
        CONNECTOR_REGISTRY[source_type] = cls
        return cls

    return decorator


def get_connector(
    source_type: SourceType,
    config: dict[str, Any],
) -> BaseConnector:
    """
    Factory: return a new connector instance for *source_type*.

    Each call constructs a fresh instance — connectors are NOT singletons.

    Raises
    ------
    ValueError
        If no connector for *source_type* has been registered.
    """
    cls = CONNECTOR_REGISTRY.get(source_type)
    if cls is None:
        registered = ", ".join(t.value for t in CONNECTOR_REGISTRY)
        raise ValueError(
            f"No connector registered for source_type={source_type!r}. "
            f"Registered types: [{registered}]"
        )
    return cls(config)
```

---

## File 3 — `app/connectors/__init__.py`

```python
"""
Connector package.

Concrete connectors MUST be imported here so their `@register` decorators
execute before `get_connector` is first called.
"""

from .base import BaseConnector, Document
from .registry import CONNECTOR_REGISTRY, get_connector, register

# Concrete connectors — imported for side-effect (registration)
from . import web_url_connector       # noqa: F401 — T-046
from . import file_upload_connector   # noqa: F401 — T-047
from . import database_connector      # noqa: F401 — T-048
from . import confluence_connector    # noqa: F401 — T-049
from . import sharepoint_connector    # noqa: F401 — T-049

__all__ = [
    "BaseConnector",
    "Document",
    "CONNECTOR_REGISTRY",
    "get_connector",
    "register",
]
```

> **Note:** The concrete connector imports will resolve after T-046–T-049 are implemented. Until then, remove the stubs or guard with `try/except ImportError`.

---

## Acceptance Criteria

- [ ] `Document` fields: `id` (UUID, auto-generated), `source_id` (UUID), `raw_text` (str), `metadata` (dict, default `{}`), `raw_storage_path` (str | None, default None)
- [ ] `BaseConnector.__init__` accepts `config: dict[str, Any]` and stores as `self._config`
- [ ] `BaseConnector.__aenter__` calls `connect()`; `__aexit__` calls `disconnect()`
- [ ] `register(source_type)` raises `RuntimeError` on duplicate registration
- [ ] `get_connector` raises `ValueError` for unregistered `SourceType`
- [ ] `get_connector` returns distinct instances on successive calls (no singleton)
- [ ] `CONNECTOR_REGISTRY` is importable and initially empty until concrete connectors are loaded
