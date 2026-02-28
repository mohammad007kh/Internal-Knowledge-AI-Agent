"""Confluence connector stub — not implemented in this release."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from src.connectors.base import BaseConnector, Document
from src.connectors.registry import register
from src.models.enums import SourceType

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

    async def extract_documents(self) -> AsyncIterator[Document]:  # type: ignore[override]
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
