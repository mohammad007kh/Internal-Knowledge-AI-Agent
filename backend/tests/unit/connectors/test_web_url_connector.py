"""Unit tests for WebUrlConnector (T-057)."""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.connectors.base import Document
from src.connectors.web_url_connector import WebUrlConnector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE_ID = str(uuid.uuid4())
_URL = "https://example.com/page"
_HTML = b"<html><body><nav>nav</nav><p>Hello World content</p><footer>f</footer></body></html>"


def _make_connector(extra: dict[str, Any] | None = None) -> tuple[WebUrlConnector, MagicMock]:
    """Return (connector, mock_storage_instance) with StorageService patched."""
    cfg: dict[str, Any] = {"url": _URL, "source_id": _SOURCE_ID, "check_robots": False}
    if extra:
        cfg.update(extra)
    with patch("src.connectors.web_url_connector.StorageService") as mock_cls:
        conn = WebUrlConnector(config=cfg)
        mock_storage = mock_cls.return_value
        # Attach so tests can configure it
        conn._storage = mock_storage  # noqa: SLF001
    return conn, mock_storage


def _http_response(status: int = 200, content: bytes = _HTML, content_type: str = "text/html") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.content = content
    resp.headers = {"content-type": content_type}
    resp.raise_for_status = MagicMock()  # no-op for 2xx; raise for 4xx/5xx handled separately
    return resp


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_constructor_stores_url() -> None:
    conn, _ = _make_connector()
    assert conn._url == _URL  # noqa: SLF001


def test_constructor_defaults() -> None:
    conn, _ = _make_connector()
    assert conn._check_robots is False  # noqa: SLF001
    assert conn._timeout == 30.0  # noqa: SLF001


def test_constructor_custom_timeout() -> None:
    conn, _ = _make_connector({"timeout": 5.0})
    assert conn._timeout == 5.0  # noqa: SLF001


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


async def test_connect_creates_client() -> None:
    conn, _ = _make_connector()
    with patch("src.connectors.web_url_connector.httpx.AsyncClient") as mock_client_cls:
        fake_client = AsyncMock()
        mock_client_cls.return_value = fake_client
        await conn.connect()
        assert conn._client is fake_client  # noqa: SLF001
        mock_client_cls.assert_called_once()


async def test_disconnect_closes_client() -> None:
    conn, _ = _make_connector()
    mock_client = AsyncMock()
    conn._client = mock_client  # noqa: SLF001
    await conn.disconnect()
    mock_client.aclose.assert_called_once()
    assert conn._client is None  # noqa: SLF001


async def test_disconnect_without_client_is_safe() -> None:
    conn, _ = _make_connector()
    assert conn._client is None  # noqa: SLF001
    await conn.disconnect()  # must not raise


# ---------------------------------------------------------------------------
# extract_documents — happy path
# ---------------------------------------------------------------------------


async def test_extract_documents_yields_one_document() -> None:
    conn, mock_storage = _make_connector()
    mock_storage.upload_bytes = AsyncMock(return_value=f"raw/web/{_SOURCE_ID}/example.com.html")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_http_response())
    conn._client = mock_client  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert len(docs) == 1


async def test_extract_documents_document_type() -> None:
    conn, mock_storage = _make_connector()
    mock_storage.upload_bytes = AsyncMock(return_value="raw/web/test/example.com.html")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_http_response())
    conn._client = mock_client  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert isinstance(docs[0], Document)


async def test_extract_documents_raw_text_contains_body_content() -> None:
    conn, mock_storage = _make_connector()
    mock_storage.upload_bytes = AsyncMock(return_value="raw/web/test/example.com.html")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_http_response())
    conn._client = mock_client  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert "Hello World content" in docs[0].raw_text


async def test_extract_documents_strips_nav_footer_header() -> None:
    """Navigation elements are stripped from the extracted text."""
    html = b"<html><body><nav>NAVIGATION</nav><p>REAL</p></body></html>"
    conn, mock_storage = _make_connector()
    mock_storage.upload_bytes = AsyncMock(return_value="raw/web/test/x.html")

    resp = _http_response(content=html)
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=resp)
    conn._client = mock_client  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert "REAL" in docs[0].raw_text
    assert "NAVIGATION" not in docs[0].raw_text


async def test_extract_documents_metadata_contains_url() -> None:
    conn, mock_storage = _make_connector()
    mock_storage.upload_bytes = AsyncMock(return_value="raw/web/test/example.com.html")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_http_response())
    conn._client = mock_client  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert docs[0].metadata["url"] == _URL


async def test_extract_documents_metadata_status_code() -> None:
    conn, mock_storage = _make_connector()
    mock_storage.upload_bytes = AsyncMock(return_value="raw/web/test/example.com.html")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_http_response(status=200))
    conn._client = mock_client  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert docs[0].metadata["status_code"] == 200


async def test_extract_documents_source_id_is_uuid() -> None:
    conn, mock_storage = _make_connector()
    mock_storage.upload_bytes = AsyncMock(return_value="raw/web/test/example.com.html")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_http_response())
    conn._client = mock_client  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert isinstance(docs[0].source_id, uuid.UUID)
    assert docs[0].source_id == uuid.UUID(_SOURCE_ID)


async def test_extract_documents_raw_storage_path_set() -> None:
    expected_path = f"raw/web/{_SOURCE_ID}/example.com.html"
    conn, mock_storage = _make_connector()
    mock_storage.upload_bytes = AsyncMock(return_value=expected_path)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_http_response())
    conn._client = mock_client  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert docs[0].raw_storage_path == expected_path


# ---------------------------------------------------------------------------
# extract_documents — MinIO failure is non-fatal
# ---------------------------------------------------------------------------


async def test_extract_documents_continues_when_minio_upload_fails() -> None:
    """A MinIO upload failure must not prevent document emission."""
    conn, mock_storage = _make_connector()
    mock_storage.upload_bytes = AsyncMock(side_effect=Exception("MinIO down"))

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=_http_response())
    conn._client = mock_client  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert len(docs) == 1
    assert docs[0].raw_storage_path is None


# ---------------------------------------------------------------------------
# extract_documents — robots.txt compliance
# ---------------------------------------------------------------------------


async def test_extract_documents_robots_disallowed_yields_nothing() -> None:
    """When robots.txt disallows the URL, no documents are emitted."""
    conn, mock_storage = _make_connector({"check_robots": True})
    mock_storage.upload_bytes = AsyncMock(return_value="raw/web/test/x.html")

    # robots.txt disallows all agents
    robots_resp = MagicMock()
    robots_resp.status_code = 200
    robots_resp.text = "User-agent: *\nDisallow: /"

    # Shouldn't reach page fetch, but set up anyway
    page_resp = _http_response()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=[robots_resp, page_resp])
    conn._client = mock_client  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert len(docs) == 0


async def test_extract_documents_robots_network_error_assumes_allowed() -> None:
    """If fetching robots.txt fails with a network error, the URL is treated as allowed."""
    conn, mock_storage = _make_connector({"check_robots": True})
    mock_storage.upload_bytes = AsyncMock(return_value="raw/web/test/x.html")

    # Page fetch returns valid HTML
    page_resp = _http_response()

    mock_client = AsyncMock()
    # First call (robots.txt) raises, second call (page) succeeds
    mock_client.get = AsyncMock(side_effect=[Exception("network error"), page_resp])
    conn._client = mock_client  # noqa: SLF001

    docs: list[Document] = []
    async for doc in conn.extract_documents():
        docs.append(doc)

    assert len(docs) == 1


# ---------------------------------------------------------------------------
# extract_documents — no client guard
# ---------------------------------------------------------------------------


async def test_extract_documents_raises_if_no_client() -> None:
    conn, _ = _make_connector()
    assert conn._client is None  # noqa: SLF001
    with pytest.raises(AssertionError):
        async for _ in conn.extract_documents():
            pass


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------


async def test_test_connection_returns_true_on_2xx() -> None:
    conn, _ = _make_connector()
    resp = MagicMock()
    resp.status_code = 200

    with patch("src.connectors.web_url_connector.httpx.AsyncClient") as mock_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.head = AsyncMock(return_value=resp)
        mock_cls.return_value = mock_ctx

        result = await conn.test_connection()

    assert result is True


async def test_test_connection_returns_false_on_4xx() -> None:
    conn, _ = _make_connector()
    resp = MagicMock()
    resp.status_code = 404

    with patch("src.connectors.web_url_connector.httpx.AsyncClient") as mock_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.head = AsyncMock(return_value=resp)
        mock_cls.return_value = mock_ctx

        result = await conn.test_connection()

    assert result is False


async def test_test_connection_returns_false_on_network_error() -> None:
    conn, _ = _make_connector()

    with patch("src.connectors.web_url_connector.httpx.AsyncClient") as mock_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.head = AsyncMock(side_effect=Exception("connection refused"))
        mock_cls.return_value = mock_ctx

        result = await conn.test_connection()

    assert result is False


async def test_test_connection_never_raises() -> None:
    conn, _ = _make_connector()

    with patch("src.connectors.web_url_connector.httpx.AsyncClient") as mock_cls:
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_ctx.head = AsyncMock(side_effect=RuntimeError("boom"))
        mock_cls.return_value = mock_ctx

        # Must not propagate
        result = await conn.test_connection()

    assert result is False


# ---------------------------------------------------------------------------
# Async context manager
# ---------------------------------------------------------------------------


async def test_async_context_manager_calls_connect_disconnect() -> None:
    conn, mock_storage = _make_connector()
    mock_storage.upload_bytes = AsyncMock(return_value="raw/web/test/x.html")

    with patch.object(conn, "connect", new_callable=AsyncMock) as mock_connect, \
         patch.object(conn, "disconnect", new_callable=AsyncMock) as mock_disconnect:
        async with conn:
            mock_connect.assert_called_once()
        mock_disconnect.assert_called_once()
