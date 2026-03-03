# T-046 â€” WebUrl Connector

**Status:** Done

## Context
```
Python 3.12 | httpx (async) Â· BeautifulSoup4 Â· MinIO (presigned PUT)
SourceType.WEB_URL Â· @register decorator Â· BaseConnector ABC
FR-020: connection strings must never appear in user-facing output
```

## Goal
Implement `WebUrlConnector`: fetch a web page (respecting `robots.txt`), extract clean text via BeautifulSoup, archive the raw HTML to MinIO, and yield a single `Document`.

---

## File â€” `app/connectors/web_url_connector.py`

```python
from __future__ import annotations

import logging
import urllib.robotparser
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.connectors.base import BaseConnector, Document
from app.connectors.registry import register
from app.models.enums import SourceType
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = "KnowledgeAIAgent/1.0 (+internal)"
_DEFAULT_TIMEOUT = 30.0  # seconds
_MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB safety limit for HTML


@register(SourceType.WEB_URL)
class WebUrlConnector(BaseConnector):
    """
    Connector for publicly accessible web URLs.

    Expected *config* keys:
        url (str, required)           â€” target page URL
        user_agent (str, optional)    â€” HTTP User-Agent header
        timeout (float, optional)     â€” request timeout in seconds
        check_robots (bool, optional) â€” default True; set False for internal URLs

    MinIO bucket key pattern: ``raw/web/{source_id}/{sanitised_domain}.html``
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._url: str = config["url"]
        self._user_agent: str = config.get("user_agent", _DEFAULT_USER_AGENT)
        self._timeout: float = float(config.get("timeout", _DEFAULT_TIMEOUT))
        self._check_robots: bool = bool(config.get("check_robots", True))
        self._client: httpx.AsyncClient | None = None
        self._storage: StorageService = StorageService()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self._user_agent},
            timeout=self._timeout,
            follow_redirects=True,
        )
        logger.info("WebUrlConnector: HTTP client initialised")

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("WebUrlConnector: HTTP client closed")

    # ------------------------------------------------------------------ #
    # robots.txt compliance
    # ------------------------------------------------------------------ #

    async def _is_allowed(self) -> bool:
        """Return True if the target URL is allow-listed by robots.txt."""
        if not self._check_robots:
            return True
        parsed = urlparse(self._url)
        robots_url = urljoin(f"{parsed.scheme}://{parsed.netloc}", "/robots.txt")
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots_url)
        try:
            assert self._client is not None
            resp = await self._client.get(robots_url)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            # Any non-200 â†’ assume allowed
        except Exception:
            # Network errors while fetching robots.txt â†’ assume allowed
            pass
        return rp.can_fetch(self._user_agent, self._url)

    # ------------------------------------------------------------------ #
    # Extraction
    # ------------------------------------------------------------------ #

    async def extract_documents(self) -> AsyncIterator[Document]:
        assert self._client is not None, "Call connect() before extract_documents()"

        if not await self._is_allowed():
            logger.warning(
                "WebUrlConnector: robots.txt disallows crawling %s â€” skipping",
                self._url,
            )
            return

        logger.info("WebUrlConnector: fetching %s", self._url)
        response = await self._client.get(self._url)
        response.raise_for_status()

        raw_html = response.content
        if len(raw_html) > _MAX_CONTENT_LENGTH:
            logger.warning(
                "WebUrlConnector: response from %s exceeds %d bytes â€” truncating",
                self._url,
                _MAX_CONTENT_LENGTH,
            )
            raw_html = raw_html[:_MAX_CONTENT_LENGTH]

        soup = BeautifulSoup(raw_html, "html.parser")

        # Remove navigation noise
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        raw_text = soup.get_text(separator="\n", strip=True)

        # Archive raw HTML to MinIO
        source_id = self._config.get("source_id", "unknown")
        parsed = urlparse(self._url)
        safe_domain = parsed.netloc.replace(":", "_")
        object_key = f"raw/web/{source_id}/{safe_domain}.html"
        raw_storage_path: str | None = None
        try:
            raw_storage_path = await self._storage.upload_bytes(
                data=raw_html,
                object_key=object_key,
                content_type="text/html",
            )
        except Exception as exc:
            logger.warning(
                "WebUrlConnector: failed to archive HTML to MinIO (%s) â€” continuing",
                exc,
            )

        yield Document(
            source_id=source_id,  # type: ignore[arg-type]
            raw_text=raw_text,
            metadata={
                "url": self._url,
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type", ""),
            },
            raw_storage_path=raw_storage_path,
        )

    # ------------------------------------------------------------------ #
    # test_connection
    # ------------------------------------------------------------------ #

    async def test_connection(self) -> bool:
        """
        Send a HEAD request to the target URL.
        Returns True only if the response HTTP status < 400.
        Never raises.
        """
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": self._user_agent},
                timeout=self._timeout,
                follow_redirects=True,
            ) as client:
                resp = await client.head(self._url)
                return resp.status_code < 400
        except Exception as exc:
            logger.warning("WebUrlConnector.test_connection failed: %s", exc)
            return False
```

---

## `app/services/storage_service.py` (Stub â€” expand in T-047)

Add `upload_bytes` if not already present:

```python
async def upload_bytes(
    self,
    data: bytes,
    object_key: str,
    content_type: str = "application/octet-stream",
) -> str:
    """
    Upload *data* to MinIO and return the object key.
    Raises on MinIO error (caller decides how to handle).
    """
    import io
    from app.core.config import get_settings
    settings = get_settings()
    self._client.put_object(
        bucket_name=settings.minio.bucket_name,
        object_name=object_key,
        data=io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return object_key
```

---

## Acceptance Criteria

- [ ] `WebUrlConnector` is auto-registered for `SourceType.WEB_URL` via `@register`
- [ ] `connect()` creates an `httpx.AsyncClient`; `disconnect()` closes it
- [ ] `extract_documents()` skips crawling and yields nothing when `robots.txt` disallows the URL
- [ ] HTML is stripped of `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>` tags before text extraction
- [ ] Raw HTML is uploaded to MinIO at `raw/web/{source_id}/{domain}.html`; `raw_storage_path` is set on `Document`
- [ ] If MinIO upload fails, the connector logs a warning and yields the `Document` anyway (no exception)
- [ ] `test_connection()` sends a HEAD request and returns `False` (not raises) on any exception or HTTP â‰¥ 400
- [ ] `_url` and `_config` are never included in log output at WARNING/ERROR level
