"""Unit tests for ``WebUrlConnector.fetch_documents`` (FX25).

Covers every documented failure mode plus a happy-path single-page fetch.
Uses ``httpx.MockTransport`` (no real network) so the suite is fast and
deterministic — and we don't pick up a new test-only dependency.
"""
from __future__ import annotations

import socket
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.connectors.web_url_connector import WebUrlConnector
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
    WebUrlFetchReason,
)
from src.connectors.web_url_errors import (
    ConnectionRefusedError as WebConnectionRefusedError,
)

_SOURCE_ID = str(uuid.uuid4())
_URL = "https://example.com/page"

# Long enough to clear the 200-char extracted-text threshold for the happy
# path; trafilatura is conservative about boilerplate so we give it ~1KB of
# real content.
_GOOD_HTML = (
    b"<!doctype html><html><head><title>Example Article</title></head>"
    b"<body><article><h1>Example Article</h1>"
    + (
        b"<p>"
        + (b"This is the article body with plenty of readable prose. " * 12)
        + b"</p>"
    )
    + b"</article></body></html>"
)


@pytest.fixture(autouse=True)
def _allow_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Treat every hostname as a public IP so the SSRF guard passes by default.

    Individual tests that want the guard to fail call ``_stub_dns`` to
    override the resolver with a private address.
    """

    def _fake(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

    monkeypatch.setattr("src.connectors.web_url_connector.socket.getaddrinfo", _fake)


def _stub_dns(monkeypatch: pytest.MonkeyPatch, ip: str) -> None:
    def _fake(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 0))]

    monkeypatch.setattr("src.connectors.web_url_connector.socket.getaddrinfo", _fake)


def _make_connector(extra: dict[str, Any] | None = None) -> WebUrlConnector:
    cfg: dict[str, Any] = {
        "url": _URL,
        "source_id": _SOURCE_ID,
        "check_robots": False,
        "crawl_mode": "single",
    }
    if extra:
        cfg.update(extra)
    with patch("src.connectors.web_url_connector.StorageService") as mock_cls:
        conn = WebUrlConnector(config=cfg)
        # Best-effort archive must be tolerant of failure — patch it to be
        # a successful no-op by default so tests don't need to think about it.
        mock_storage = mock_cls.return_value
        mock_storage.upload_bytes = AsyncMock(
            return_value=f"raw/web/{_SOURCE_ID}/example.com.html"
        )
        conn._storage = mock_storage  # noqa: SLF001
    return conn


def _install_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Any
) -> None:
    """Force ``httpx.AsyncClient`` inside the connector to use a MockTransport."""

    original_ctor = httpx.AsyncClient

    def _wrapped(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_ctor(*args, **kwargs)

    monkeypatch.setattr(
        "src.connectors.web_url_connector.httpx.AsyncClient", _wrapped
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_fetch_documents_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_GOOD_HTML,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    _install_transport(monkeypatch, handler)

    conn = _make_connector()
    docs = await conn.fetch_documents()

    assert len(docs) == 1
    doc = docs[0]
    assert doc.url == _URL
    assert "readable prose" in doc.content
    assert doc.metadata["document_title"]
    assert doc.metadata["source_url"] == _URL
    assert doc.metadata["status_code"] == 200
    assert "fetched_at" in doc.metadata


async def test_fetch_documents_archives_to_minio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_GOOD_HTML,
            headers={"content-type": "text/html"},
        )

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    await conn.fetch_documents()
    conn._storage.upload_bytes.assert_awaited_once()  # noqa: SLF001


# ---------------------------------------------------------------------------
# SSRF / DNS / connectivity failures
# ---------------------------------------------------------------------------


async def test_blocked_address_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_dns(monkeypatch, "10.0.0.1")
    conn = _make_connector()
    with pytest.raises(BlockedAddressError) as ei:
        await conn.fetch_documents()
    assert "private/internal" in ei.value.user_message


async def test_blocked_address_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_dns(monkeypatch, "127.0.0.1")
    conn = _make_connector()
    with pytest.raises(BlockedAddressError):
        await conn.fetch_documents()


async def test_blocked_address_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    # The literal host blocklist fires before DNS, so DNS can resolve to
    # anything here.
    conn = _make_connector({"url": "http://169.254.169.254/latest/meta-data/"})
    with pytest.raises(BlockedAddressError):
        await conn.fetch_documents()


async def test_dns_failure_surfaces_dns_resolution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``ConnectError`` whose cause is ``socket.gaierror`` → DNS message."""

    def handler(request: httpx.Request) -> httpx.Response:
        err = httpx.ConnectError("name resolution failed")
        err.__cause__ = socket.gaierror("no such host")
        raise err

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(DnsResolutionError) as ei:
        await conn.fetch_documents()
    assert "could not be resolved" in ei.value.user_message


async def test_connection_refused_surfaces_connection_refused_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(WebConnectionRefusedError) as ei:
        await conn.fetch_documents()
    assert "refused the connection" in ei.value.user_message


async def test_timeout_surfaces_request_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(RequestTimeoutError) as ei:
        await conn.fetch_documents()
    assert "15 seconds" in ei.value.user_message


# ---------------------------------------------------------------------------
# HTTP status failures
# ---------------------------------------------------------------------------


async def test_http_404_surfaces_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(HttpClientError) as ei:
        await conn.fetch_documents()
    assert "404" in ei.value.user_message


@pytest.mark.parametrize("status", [401, 403])
async def test_http_auth_required(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="Forbidden")

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(HttpAuthRequiredError) as ei:
        await conn.fetch_documents()
    assert "login wall" in ei.value.user_message
    assert str(status) in ei.value.user_message


async def test_http_500_surfaces_server_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(HttpServerError) as ei:
        await conn.fetch_documents()
    assert "503" in ei.value.user_message


# ---------------------------------------------------------------------------
# Content-Type / size / extraction failures
# ---------------------------------------------------------------------------


async def test_non_html_content_type_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"%PDF-1.4 ...",
            headers={"content-type": "application/pdf"},
        )

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(UnsupportedContentTypeError) as ei:
        await conn.fetch_documents()
    assert "application/pdf" in ei.value.user_message
    assert "PDF" in ei.value.user_message


async def test_json_content_type_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'{"hello":"world"}',
            headers={"content-type": "application/json"},
        )

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(UnsupportedContentTypeError) as ei:
        await conn.fetch_documents()
    assert "application/json" in ei.value.user_message


async def test_oversize_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    big = b"<html><body>" + (b"a" * (6 * 1024 * 1024)) + b"</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=big,
            headers={"content-type": "text/html"},
        )

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(ContentTooLargeError) as ei:
        await conn.fetch_documents()
    assert "5MB" in ei.value.user_message


async def test_empty_content_after_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A near-empty SPA shell yields no readable text — surface that distinctly."""
    spa_shell = (
        b"<!doctype html><html><head><title>app</title></head>"
        b"<body><div id='root'></div><script>/* JS-only */</script></body>"
        b"</html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=spa_shell, headers={"content-type": "text/html"}
        )

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(EmptyContentError) as ei:
        await conn.fetch_documents()
    assert "no readable text" in ei.value.user_message


# ---------------------------------------------------------------------------
# Redirect handling
# ---------------------------------------------------------------------------


async def test_cross_domain_redirect_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(
                301, headers={"location": "https://other.example/page"}
            )
        return httpx.Response(
            200,
            content=_GOOD_HTML,
            headers={"content-type": "text/html"},
        )

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(CrossDomainRedirectError) as ei:
        await conn.fetch_documents()
    assert "other.example" in ei.value.user_message


async def test_redirect_into_private_address_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 302 to an internal host MUST trip the SSRF guard, not be followed."""
    call_count = {"n": 0}

    def dns(host: str, *args: Any, **kwargs: Any) -> list[Any]:
        if host == "internal.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", 0))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(
        "src.connectors.web_url_connector.socket.getaddrinfo", dns
    )

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(
            302, headers={"location": "https://internal.example.com/secret"}
        )

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    with pytest.raises(BlockedAddressError):
        await conn.fetch_documents()
    # Only the first hop was made; the redirect target was rejected pre-network.
    assert call_count["n"] == 1


async def test_same_domain_redirect_is_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hops: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hops.append(str(request.url))
        if str(request.url) == _URL:
            return httpx.Response(
                301, headers={"location": "https://example.com/page-final"}
            )
        return httpx.Response(
            200,
            content=_GOOD_HTML,
            headers={"content-type": "text/html"},
        )

    _install_transport(monkeypatch, handler)
    conn = _make_connector()
    docs = await conn.fetch_documents()
    assert len(docs) == 1
    assert docs[0].url.endswith("/page-final")
    assert len(hops) == 2


# ---------------------------------------------------------------------------
# Crawl mode guard
# ---------------------------------------------------------------------------


async def test_recursive_crawl_mode_is_rejected() -> None:
    conn = _make_connector({"crawl_mode": "recursive"})
    with pytest.raises(UnsupportedCrawlModeError) as ei:
        await conn.fetch_documents()
    assert "Unsupported crawl_mode" in ei.value.user_message


# ---------------------------------------------------------------------------
# Reason enum coverage — every distinct subclass has a stable identifier
# ---------------------------------------------------------------------------


def test_every_failure_mode_has_distinct_reason() -> None:
    seen = {
        BlockedAddressError().reason,
        WebConnectionRefusedError().reason,
        RequestTimeoutError(15.0).reason,
        HttpClientError(404, "Not Found").reason,
        HttpAuthRequiredError(401).reason,
        HttpServerError(503).reason,
        UnsupportedContentTypeError("application/pdf").reason,
        ContentTooLargeError(5 * 1024 * 1024).reason,
        CrossDomainRedirectError("evil.example").reason,
        EmptyContentError().reason,
        DnsResolutionError("nope.invalid").reason,
        UnsupportedCrawlModeError("recursive").reason,
    }
    assert len(seen) == len(WebUrlFetchReason)
