"""WebUrl connector — fetch, parse, archive, and yield a Document (T-046)."""
from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.robotparser
import uuid
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector, Document
from src.connectors.registry import register
from src.models.enums import SourceType
from src.services.storage_service import StorageService

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = "KnowledgeAIAgent/1.0 (+internal)"
_DEFAULT_TIMEOUT = 30.0  # seconds
_MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB safety limit for HTML

# Hostnames we always reject regardless of DNS resolution. ``169.254.169.254``
# is also covered by the link-local check below; listed here for symmetry.
_BLOCKED_HOSTS: frozenset[str] = frozenset(
    {"metadata.google.internal", "metadata", "169.254.169.254"}
)


def _is_safe_url(url: str) -> bool:
    """Return ``True`` only when *url* points to a publicly routable host.

    Resolves all A/AAAA records for the hostname and rejects any address that
    is private, loopback, link-local, multicast, reserved, or otherwise
    non-public. This guards the connector against SSRF attacks that try to
    exfiltrate cloud-metadata services or pivot into the internal network.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host or host in _BLOCKED_HOSTS:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        sockaddr = info[4]
        try:
            addr = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return False
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
            or addr.is_unspecified
        ):
            return False
    return True


@register(SourceType.WEB_URL)
class WebUrlConnector(BaseConnector):
    """
    Connector for publicly accessible web URLs.

    Expected *config* keys:
        url (str, required)           — target page URL
        source_id (str, required)     — UUID string of the parent Source row
        user_agent (str, optional)    — HTTP User-Agent header
        timeout (float, optional)     — request timeout in seconds
        check_robots (bool, optional) — default True; set False for internal URLs

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
            # Any non-200 → assume allowed
        except Exception:  # noqa: BLE001
            # Network errors while fetching robots.txt → assume allowed
            return True
        return rp.can_fetch(self._user_agent, self._url)

    # ------------------------------------------------------------------ #
    # Extraction
    # ------------------------------------------------------------------ #

    async def extract_documents(self) -> AsyncIterator[Document]:
        assert self._client is not None, "Call connect() before extract_documents()"

        if not _is_safe_url(self._url):
            raise ValueError(
                "URL points to a non-public address; refusing to fetch."
            )

        if not await self._is_allowed():
            logger.warning(
                "WebUrlConnector: robots.txt disallows crawling — skipping",
            )
            return

        logger.info("WebUrlConnector: fetching page")
        response = await self._client.get(self._url)
        response.raise_for_status()

        raw_html = response.content
        if len(raw_html) > _MAX_CONTENT_LENGTH:
            logger.warning(
                "WebUrlConnector: response exceeds %d bytes — truncating",
                _MAX_CONTENT_LENGTH,
            )
            raw_html = raw_html[:_MAX_CONTENT_LENGTH]

        soup = BeautifulSoup(raw_html, "html.parser")

        # Remove navigation noise
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        raw_text = soup.get_text(separator="\n", strip=True)

        # Archive raw HTML to MinIO
        source_id_raw = self._config.get("source_id", "")
        source_uuid = uuid.UUID(str(source_id_raw)) if source_id_raw else uuid.uuid4()
        parsed = urlparse(self._url)
        safe_domain = parsed.netloc.replace(":", "_")
        object_key = f"raw/web/{source_uuid}/{safe_domain}.html"
        raw_storage_path: str | None = None
        try:
            raw_storage_path = await self._storage.upload_bytes(
                data=raw_html,
                object_key=object_key,
                content_type="text/html",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "WebUrlConnector: failed to archive HTML to MinIO — continuing: %s",
                type(exc).__name__,
            )

        yield Document(
            source_id=source_uuid,
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
        if not _is_safe_url(self._url):
            logger.warning("WebUrlConnector.test_connection: SSRF guard rejected URL")
            return False
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": self._user_agent},
                timeout=self._timeout,
                follow_redirects=True,
            ) as client:
                resp = await client.head(self._url)
                return resp.status_code < 400
        except Exception as exc:  # noqa: BLE001
            logger.warning("WebUrlConnector.test_connection failed: %s", type(exc).__name__)
            return False
