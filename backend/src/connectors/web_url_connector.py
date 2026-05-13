"""WebUrl connector — fetch, parse, archive, and yield Documents (T-046 + FX25).

Two surfaces:

``extract_documents`` (legacy, T-046)
    Async-generator API used by older callers; yields ``Document`` rows
    one at a time.  Kept unchanged for back-compat — see existing tests.

``fetch_documents`` (FX25)
    The list-returning API used by the Celery sync pipeline
    (``tasks.sync_source``).  Single-page mode for now (the wizard only
    exposes ``crawl_mode='single'`` — recursive crawl is out of scope).

    Specific failure modes raise concrete :class:`WebUrlFetchError`
    subclasses so the sync orchestrator can surface a user-actionable
    message verbatim on the failed Source row.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.robotparser
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from src.connectors.base import BaseConnector, Document
from src.connectors.registry import register
from src.connectors.web_url_errors import (
    BlockedAddressError,
    ContentTooLargeError,
    CrossDomainRedirectError,
    DnsResolutionError,
    EmptyContentError,
    HttpAuthRequiredError,
    HttpClientError,
    HttpServerError,
    RequestTimeoutError,
    UnsupportedContentTypeError,
    UnsupportedCrawlModeError,
    WebUrlFetchError,
)
# ``ConnectionRefusedError`` is also a Python built-in. Importing under a
# private alias keeps the built-in identifier intact at module scope so we
# don't accidentally shadow it for any third-party library on the stack.
from src.connectors.web_url_errors import (
    ConnectionRefusedError as _WebConnectionRefusedError,
)
from src.models.enums import SourceType
from src.schemas.raw_document import RawDocument
from src.services.storage_service import StorageService

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = "KnowledgeAIAgent/1.0 (+internal)"
_DEFAULT_TIMEOUT = 30.0  # seconds — legacy extract_documents() default

# Single-page fetch budget (FX25). Hard-cap below the legacy limit so a
# large response cannot starve a worker. The orchestrator gives up after
# this many seconds; we never read more than this many bytes either.
_FETCH_TIMEOUT_SECONDS = 15.0
_MAX_REDIRECTS = 3
_MAX_BYTES = 5 * 1024 * 1024  # 5MB
_MIN_EXTRACTED_CHARS = 200

# MIME types we accept as "a web page". Anything else routes through
# UnsupportedContentTypeError so the admin sees "use file upload for PDFs",
# "use a database source for APIs", etc.
_HTML_CONTENT_TYPES: frozenset[str] = frozenset(
    {"text/html", "application/xhtml+xml"}
)

_MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB legacy limit for extract_documents

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


def _hostname(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _has_cause(exc: BaseException, target: type[BaseException]) -> bool:
    """Walk the ``__cause__`` / ``__context__`` chain looking for *target*."""
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, target):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


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
        crawl_mode (str, optional)    — only "single" is supported today

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
    # Extraction (legacy generator API — kept for back-compat, T-046)
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
    # fetch_documents — list-returning API used by the Celery sync pipeline
    # ------------------------------------------------------------------ #

    async def fetch_documents(self) -> list[RawDocument]:
        """Single-page fetch with explicit, user-actionable failure modes.

        Pipeline:

        1. SSRF guard against the originally-requested URL.
        2. Manual redirect loop (up to ``_MAX_REDIRECTS``); re-runs the
           SSRF guard against every ``Location`` target so a server can't
           bounce the worker into the internal network.  Cross-domain
           redirects are rejected inside the loop (before the body is
           even requested).
        3. Stream the response body and abort once we cross ``_MAX_BYTES``.
        4. Reject anything that isn't ``text/html`` /
           ``application/xhtml+xml``.
        5. Extract main content via trafilatura → fall back to
           readability-lxml → if both yield < 200 chars, raise
           :class:`EmptyContentError`.
        6. Archive the raw HTML to MinIO best-effort.
        7. Return one :class:`RawDocument` with metadata the persist
           pipeline (FX17 / A.2) projects onto chunks: ``document_title``,
           ``source_url``, ``fetched_at``, ``status_code``,
           ``content_type``.  ``source_name`` is injected downstream by
           ``tasks.sync_source`` from the Source row itself.

        Crawl modes other than ``single`` are rejected up-front — see
        :class:`WebUrlFetchError` for the documented contract.
        """
        crawl_mode = str(self._config.get("crawl_mode", "single")).lower()
        if crawl_mode != "single":
            raise UnsupportedCrawlModeError(crawl_mode)

        # 1. Initial SSRF guard.
        if not _is_safe_url(self._url):
            raise BlockedAddressError()

        async with httpx.AsyncClient(
            headers={"User-Agent": self._user_agent},
            timeout=httpx.Timeout(_FETCH_TIMEOUT_SECONDS),
            follow_redirects=False,
        ) as client:
            # Cross-domain redirects are caught inside the loop (before the
            # body is even requested) — see ``_stream_with_redirects``.
            response, final_url = await self._stream_with_redirects(client)

        # Content-Type — header check + cheap sniff.
        content_type_header = response["content_type"]
        content_type = content_type_header.split(";", 1)[0].strip().lower()
        if content_type not in _HTML_CONTENT_TYPES:
            # Try a magic-byte sniff before giving up — some servers don't
            # set Content-Type but still serve HTML.
            if not _looks_like_html(response["body"]):
                raise UnsupportedContentTypeError(
                    content_type_header or "an unknown content type"
                )

        # 6. Main-content extraction.
        body_bytes: bytes = response["body"]
        title, text = _extract_main_content(body_bytes, final_url)

        if len(text.strip()) < _MIN_EXTRACTED_CHARS:
            raise EmptyContentError()

        # 7. Best-effort archive to MinIO.
        source_id_raw = self._config.get("source_id", "")
        source_uuid = (
            uuid.UUID(str(source_id_raw)) if source_id_raw else uuid.uuid4()
        )
        parsed = urlparse(final_url)
        safe_domain = parsed.netloc.replace(":", "_") or "page"
        object_key = f"raw/web/{source_uuid}/{safe_domain}.html"
        try:
            await self._storage.upload_bytes(
                data=body_bytes,
                object_key=object_key,
                content_type="text/html",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "WebUrlConnector: failed to archive HTML to MinIO — continuing: %s",
                type(exc).__name__,
            )

        # 8. Compose RawDocument.
        title = title.strip() or _fallback_title_from_url(final_url)
        metadata: dict[str, Any] = {
            "document_title": title,
            "source_url": final_url,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "status_code": response["status"],
            "content_type": content_type_header,
        }
        return [
            RawDocument(
                title=title,
                content=text,
                url=final_url,
                metadata=metadata,
            )
        ]

    # ------------------------------------------------------------------ #
    # Internal HTTP helpers
    # ------------------------------------------------------------------ #

    async def _stream_with_redirects(
        self, client: httpx.AsyncClient
    ) -> tuple[dict[str, Any], str]:
        """Drive a manual redirect loop and stream the final body.

        Returns a ``(response_meta, final_url)`` tuple where ``response_meta``
        is a flat dict — ``{status, content_type, body}`` — extracted from
        the actual response.  Driving the loop manually lets us re-check
        the SSRF guard against every ``Location`` target (httpx's built-in
        ``follow_redirects=True`` would do the network round-trip first).
        """
        current_url = self._url
        for hop in range(_MAX_REDIRECTS + 1):
            try:
                async with client.stream("GET", current_url) as resp:
                    status = resp.status_code
                    # 3xx — manual redirect.
                    if 300 <= status < 400:
                        location = resp.headers.get("location")
                        if not location:
                            # No Location → treat as final response.
                            body = await self._read_capped_body(resp)
                            return (
                                {
                                    "status": status,
                                    "content_type": resp.headers.get(
                                        "content-type", ""
                                    ),
                                    "body": body,
                                },
                                str(resp.url),
                            )
                        # Resolve relative redirects.
                        next_url = urljoin(current_url, location)
                        # Scheme guard: http→https is fine, but http→file://
                        # or http→gopher:// must be blocked — they're as
                        # dangerous as an SSRF.
                        parsed_next = urlparse(next_url)
                        if parsed_next.scheme not in ("http", "https"):
                            raise BlockedAddressError()
                        if not _is_safe_url(next_url):
                            raise BlockedAddressError()
                        # Cross-domain check: refuse to follow a redirect
                        # off the originally-requested host.  Catches
                        # http://canonical → http://aggregator scenarios
                        # before we burn bandwidth on the new host.
                        if _hostname(next_url) != _hostname(self._url):
                            raise CrossDomainRedirectError(
                                _hostname(next_url)
                            )
                        current_url = next_url
                        if hop >= _MAX_REDIRECTS:
                            # One last shot would put us over the limit.
                            raise HttpClientError(
                                status, "Too many redirects"
                            )
                        continue

                    # 4xx / 5xx — surface as a specific error.
                    if status in (401, 403):
                        raise HttpAuthRequiredError(status)
                    if 400 <= status < 500:
                        raise HttpClientError(
                            status, resp.reason_phrase or "Client Error"
                        )
                    if 500 <= status < 600:
                        raise HttpServerError(status)

                    # 2xx — stream the body, hard-capped.
                    body = await self._read_capped_body(resp)
                    return (
                        {
                            "status": status,
                            "content_type": resp.headers.get("content-type", ""),
                            "body": body,
                        },
                        str(resp.url),
                    )
            except httpx.TimeoutException as exc:
                raise RequestTimeoutError(_FETCH_TIMEOUT_SECONDS) from exc
            except WebUrlFetchError:
                raise
            except httpx.ConnectError as exc:
                # httpx raises ConnectError both for DNS failures and for
                # "connection refused".  Differentiate by walking the
                # exception chain for a ``socket.gaierror`` — that's the
                # name-resolution failure marker.
                if _has_cause(exc, socket.gaierror):
                    host = _hostname(current_url)
                    raise DnsResolutionError(host) from exc
                raise _WebConnectionRefusedError() from exc
            except (
                httpx.ReadError,
                httpx.WriteError,
                httpx.NetworkError,
            ) as exc:
                raise _WebConnectionRefusedError() from exc

        # Loop exited without a return — should be unreachable.
        raise HttpClientError(0, "Redirect loop exited without a response")

    @staticmethod
    async def _read_capped_body(resp: httpx.Response) -> bytes:
        """Stream the response body and abort if we exceed ``_MAX_BYTES``."""
        total = 0
        chunks: list[bytes] = []
        async for chunk in resp.aiter_bytes():
            total += len(chunk)
            if total > _MAX_BYTES:
                raise ContentTooLargeError(_MAX_BYTES)
            chunks.append(chunk)
        return b"".join(chunks)

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


# ---------------------------------------------------------------------------
# Free helpers
# ---------------------------------------------------------------------------


def _looks_like_html(body: bytes) -> bool:
    """Quick sniff: does the first ~1KB contain an HTML-looking marker?"""
    head = body[:1024].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<body" in head


def _extract_main_content(body: bytes, url: str) -> tuple[str, str]:
    """Run trafilatura first, fall back to readability-lxml.

    Returns ``(title, body_text)``.  Either may be empty on failure — the
    caller decides whether the combined output crosses the "readable
    content" threshold.
    """
    text = ""
    title = ""
    try:
        import trafilatura  # noqa: PLC0415

        # Decode best-effort; trafilatura accepts either bytes or str.
        decoded = body.decode("utf-8", errors="replace")
        extracted = trafilatura.extract(
            decoded,
            url=url,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
            with_metadata=False,
        )
        if extracted:
            text = extracted

        meta = trafilatura.extract_metadata(decoded)
        if meta and meta.title:
            title = meta.title
    except Exception:  # noqa: BLE001
        logger.warning(
            "WebUrlConnector: trafilatura extract failed — falling back",
            exc_info=True,
        )

    if len(text.strip()) >= _MIN_EXTRACTED_CHARS:
        return title, text

    # Fallback — readability-lxml.
    try:
        from readability import Document as ReadabilityDoc  # noqa: PLC0415

        doc = ReadabilityDoc(body.decode("utf-8", errors="replace"))
        summary_html = doc.summary(html_partial=True)
        soup = BeautifulSoup(summary_html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        fallback_text = soup.get_text(separator="\n", strip=True)
        if not title:
            title = (doc.short_title() or "").strip()
        if len(fallback_text.strip()) > len(text.strip()):
            text = fallback_text
    except Exception:  # noqa: BLE001
        logger.warning(
            "WebUrlConnector: readability fallback failed",
            exc_info=True,
        )

    # Final safety-net — plain bs4 strip.
    if len(text.strip()) < _MIN_EXTRACTED_CHARS:
        try:
            soup = BeautifulSoup(body, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            stripped = soup.get_text(separator="\n", strip=True)
            if len(stripped.strip()) > len(text.strip()):
                text = stripped
            if not title and soup.title and soup.title.string:
                title = soup.title.string.strip()
        except Exception:  # noqa: BLE001
            logger.warning(
                "WebUrlConnector: bs4 final-fallback failed",
                exc_info=True,
            )

    return title, text


def _fallback_title_from_url(url: str) -> str:
    """Derive a human-ish title from a URL when no <title> was extractable."""
    parsed = urlparse(url)
    path = (parsed.path or "/").rstrip("/")
    if not path or path == "":
        return parsed.netloc or url
    last = path.rsplit("/", 1)[-1]
    return last.replace("-", " ").replace("_", " ") or parsed.netloc or url
