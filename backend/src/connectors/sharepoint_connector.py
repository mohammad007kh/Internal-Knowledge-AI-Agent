"""SharePoint connector stub — not implemented in this release."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from src.connectors.base import BaseConnector, Document
from src.connectors.registry import register
from src.models.enums import SourceType

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

    async def extract_documents(self) -> AsyncIterator[Document]:  # type: ignore[override]
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
