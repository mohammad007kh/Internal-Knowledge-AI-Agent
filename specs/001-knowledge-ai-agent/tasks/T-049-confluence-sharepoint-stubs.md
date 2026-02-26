# T-049 — Confluence & SharePoint Connector Stubs

## Context
```
Python 3.12 | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector
Next.js 15 App Router · shadcn/ui · Tailwind CSS v4
PostgreSQL 16 + pgvector · Celery + Redis · MinIO
JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC
Fernet (connection configs at rest)
LangGraph 8-node · Langfuse self-hosted
RFC 7807 Problem Details — all non-2xx API responses
Docker Compose 9 services
```

## Goal
Create **stub implementations** for `ConfluenceConnector` and `SharePointConnector`.
Both register themselves in the connector registry so the factory can instantiate them
by `SourceType`, but every method raises `NotImplementedError` (or returns `False` for
`test_connection`) to prevent accidental invocation in the current release.

---

## File 1 — `app/connectors/confluence_connector.py`

```python
"""Confluence connector stub — not implemented in this release."""
from __future__ import annotations

import logging
from typing import AsyncIterator

from app.connectors.base import BaseConnector, Document
from app.connectors.registry import register
from app.models.enums import SourceType

logger = logging.getLogger(__name__)


@register(SourceType.CONFLUENCE)
class ConfluenceConnector(BaseConnector):
    """
    Stub connector for Atlassian Confluence.

    Config keys (reserved for future use):
        base_url       str  — Confluence base URL, e.g. https://myorg.atlassian.net
        username       str  — Atlassian account email
        api_token      str  — Atlassian API token (stored encrypted)
        space_key      str  — Confluence space key, e.g. "ENG"
        include_pages  bool — include regular pages (default True)
        include_blogs  bool — include blog posts (default False)

    All methods raise NotImplementedError until a future release implements them.
    test_connection() returns False (never raises) to satisfy BaseConnector contract.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        raise NotImplementedError(
            "ConfluenceConnector is not implemented in this release."
        )

    async def disconnect(self) -> None:
        raise NotImplementedError(
            "ConfluenceConnector is not implemented in this release."
        )

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    async def extract_documents(self) -> AsyncIterator[Document]:
        raise NotImplementedError(
            "ConfluenceConnector is not implemented in this release."
        )
        # Required to satisfy the AsyncIterator return type annotation.
        # This branch is unreachable but keeps mypy/pyright happy.
        yield  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def test_connection(self) -> bool:
        """
        Always returns False — connector not yet implemented.

        Returns False rather than raising so the generic test-connection
        endpoint can give the caller a clean "unsupported" response
        without an unhandled 500.
        """
        logger.info(
            "test_connection called on ConfluenceConnector stub — returning False"
        )
        return False
```

---

## File 2 — `app/connectors/sharepoint_connector.py`

```python
"""SharePoint connector stub — not implemented in this release."""
from __future__ import annotations

import logging
from typing import AsyncIterator

from app.connectors.base import BaseConnector, Document
from app.connectors.registry import register
from app.models.enums import SourceType

logger = logging.getLogger(__name__)


@register(SourceType.SHAREPOINT)
class SharePointConnector(BaseConnector):
    """
    Stub connector for Microsoft SharePoint / OneDrive.

    Config keys (reserved for future use):
        tenant_id      str  — Azure AD tenant ID
        client_id      str  — Azure App Registration client ID
        client_secret  str  — Azure App Registration secret (stored encrypted)
        site_url       str  — SharePoint site URL
        library_name   str  — Document library name (default "Documents")
        recursive      bool — recurse into sub-folders (default True)

    All methods raise NotImplementedError until a future release implements them.
    test_connection() returns False (never raises) to satisfy BaseConnector contract.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        raise NotImplementedError(
            "SharePointConnector is not implemented in this release."
        )

    async def disconnect(self) -> None:
        raise NotImplementedError(
            "SharePointConnector is not implemented in this release."
        )

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------

    async def extract_documents(self) -> AsyncIterator[Document]:
        raise NotImplementedError(
            "SharePointConnector is not implemented in this release."
        )
        yield  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    async def test_connection(self) -> bool:
        """
        Always returns False — connector not yet implemented.
        """
        logger.info(
            "test_connection called on SharePointConnector stub — returning False"
        )
        return False
```

---

## Update — `app/connectors/__init__.py`

Remove the `try/except ImportError` guards added in T-045 for these two connectors now
that the stubs exist. The final file should import all five connectors unconditionally:

```python
"""
Connector package — imports register all concrete connectors into CONNECTOR_REGISTRY.
Import order does not matter; each connector self-registers via @register().
"""
from app.connectors.base import BaseConnector, Document
from app.connectors.registry import CONNECTOR_REGISTRY, get_connector, register

# Concrete implementations — side-effect imports trigger @register()
from app.connectors.confluence_connector import ConfluenceConnector  # noqa: F401
from app.connectors.database_connector import DatabaseConnector  # noqa: F401
from app.connectors.file_upload_connector import FileUploadConnector  # noqa: F401
from app.connectors.sharepoint_connector import SharePointConnector  # noqa: F401
from app.connectors.web_url_connector import WebUrlConnector  # noqa: F401

__all__ = [
    "BaseConnector",
    "Document",
    "CONNECTOR_REGISTRY",
    "get_connector",
    "register",
    "ConfluenceConnector",
    "DatabaseConnector",
    "FileUploadConnector",
    "SharePointConnector",
    "WebUrlConnector",
]
```

---

## Acceptance Criteria

1. `ConfluenceConnector` is decorated with `@register(SourceType.CONFLUENCE)` and
   appears in `CONNECTOR_REGISTRY` after import.
2. `SharePointConnector` is decorated with `@register(SourceType.SHAREPOINT)` and
   appears in `CONNECTOR_REGISTRY` after import.
3. `get_connector(SourceType.CONFLUENCE, {})` returns a `ConfluenceConnector` instance
   without raising.
4. `get_connector(SourceType.SHAREPOINT, {})` returns a `SharePointConnector` instance
   without raising.
5. `await connector.connect()` raises `NotImplementedError` for both stubs.
6. `await connector.extract_documents()` raises `NotImplementedError` for both stubs.
7. `await connector.test_connection()` returns `False` (not raises) for both stubs.
8. `CONNECTOR_REGISTRY` contains exactly 5 keys after importing `app.connectors`:
   `WEB_URL`, `FILE_UPLOAD`, `DATABASE`, `CONFLUENCE`, `SHAREPOINT`.
9. `app/connectors/__init__.py` imports all five connectors unconditionally (no
   `try/except ImportError` guards remain).
