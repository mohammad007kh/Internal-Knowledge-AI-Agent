# T-057 — Connector Unit Tests

## Context
```
Python 3.12 · pytest · pytest-asyncio · asyncio_mode=auto
httpx AsyncClient (mock transport) · unittest.mock · pytest-mock
FR-020: connection strings must NEVER appear in logged output
```

## Goal
Full unit-test coverage for all four connector implementations and the connector factory.

---

## File 1 — `tests/unit/connectors/test_web_url_connector.py`

```python
"""Unit tests for WebUrlConnector."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.connectors.web_url import WebUrlConnector


def _make_connector(url: str = "https://example.com") -> WebUrlConnector:
    return WebUrlConnector(
        source_id="00000000-0000-0000-0000-000000000001",
        config={"url": url},
    )


class TestRobotsTxt:
    async def test_allowed_when_no_robots_txt(self) -> None:
        conn = _make_connector()
        with patch("httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            # 404 for robots.txt
            client.get = AsyncMock(
                side_effect=[
                    MagicMock(status_code=404, text=""),
                    MagicMock(
                        status_code=200,
                        text="<html><body>Hello world</body></html>",
                        headers={"content-type": "text/html"},
                    ),
                ]
            )
            mock_cls.return_value.__aenter__.return_value = client
            docs = await conn.extract()
        assert len(docs) == 1

    async def test_disallowed_path_returns_empty(self) -> None:
        conn = _make_connector()
        robots_body = "User-agent: *\nDisallow: /"
        with patch("httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            client.get = AsyncMock(
                return_value=MagicMock(status_code=200, text=robots_body)
            )
            mock_cls.return_value.__aenter__.return_value = client
            docs = await conn.extract()
        assert docs == []

    async def test_allowed_specific_path(self) -> None:
        conn = _make_connector("https://example.com/docs/")
        robots_body = "User-agent: *\nDisallow: /admin/"
        with patch("httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            client.get = AsyncMock(
                side_effect=[
                    MagicMock(status_code=200, text=robots_body),
                    MagicMock(
                        status_code=200,
                        text="<html><body>Docs</body></html>",
                        headers={"content-type": "text/html"},
                    ),
                ]
            )
            mock_cls.return_value.__aenter__.return_value = client
            docs = await conn.extract()
        assert len(docs) == 1


class TestHtmlExtraction:
    async def test_strips_scripts_and_styles(self) -> None:
        conn = _make_connector()
        html = (
            "<html><head><style>.x{}</style><script>alert(1)</script></head>"
            "<body><p>Clean text</p></body></html>"
        )
        with patch("httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            client.get = AsyncMock(
                side_effect=[
                    MagicMock(status_code=404, text=""),
                    MagicMock(status_code=200, text=html,
                              headers={"content-type": "text/html"}),
                ]
            )
            mock_cls.return_value.__aenter__.return_value = client
            docs = await conn.extract()
        assert "Clean text" in docs[0].content
        assert "alert" not in docs[0].content
        assert ".x{}" not in docs[0].content

    async def test_truncates_at_10mb(self) -> None:
        conn = _make_connector()
        big_html = "<html><body>" + "x" * (11 * 1024 * 1024) + "</body></html>"
        with patch("httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            client.get = AsyncMock(
                side_effect=[
                    MagicMock(status_code=404, text=""),
                    MagicMock(status_code=200, text=big_html,
                              headers={"content-type": "text/html"}),
                ]
            )
            mock_cls.return_value.__aenter__.return_value = client
            docs = await conn.extract()
        assert len(docs[0].content) <= 10 * 1024 * 1024 + 500  # small BeautifulSoup overhead ok

    async def test_http_error_returns_empty(self) -> None:
        conn = _make_connector()
        with patch("httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_cls.return_value.__aenter__.return_value = client
            docs = await conn.extract()
        assert docs == []

    async def test_metadata_includes_source_url(self) -> None:
        conn = _make_connector("https://example.com/page")
        with patch("httpx.AsyncClient") as mock_cls:
            client = AsyncMock()
            client.get = AsyncMock(
                side_effect=[
                    MagicMock(status_code=404, text=""),
                    MagicMock(status_code=200,
                              text="<html><body>Hello</body></html>",
                              headers={"content-type": "text/html"}),
                ]
            )
            mock_cls.return_value.__aenter__.return_value = client
            docs = await conn.extract()
        assert docs[0].metadata["url"] == "https://example.com/page"
```

---

## File 2 — `tests/unit/connectors/test_file_upload_connector.py`

```python
"""Unit tests for FileUploadConnector."""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from app.connectors.file_upload import FileUploadConnector


def _make_connector(path: str, size_bytes: int = 1024) -> FileUploadConnector:
    return FileUploadConnector(
        source_id="00000000-0000-0000-0000-000000000002",
        config={"storage_path": path, "file_size_bytes": size_bytes},
    )


class TestPdfExtraction:
    async def test_pdf_extracts_pages(self) -> None:
        conn = _make_connector("uploads/doc.pdf")
        page = MagicMock()
        page.extract_text.return_value = "Page content"
        reader = MagicMock()
        reader.pages = [page, page]
        with patch("PyPDF2.PdfReader", return_value=reader):
            with patch("app.connectors.file_upload.FileUploadConnector._read_minio",
                       return_value=io.BytesIO(b"%PDF")):
                docs = await conn.extract()
        assert len(docs) == 2
        assert docs[0].content == "Page content"

    async def test_empty_pdf_skips_blank_pages(self) -> None:
        conn = _make_connector("uploads/empty.pdf")
        page = MagicMock()
        page.extract_text.return_value = "   \n  "
        reader = MagicMock()
        reader.pages = [page]
        with patch("PyPDF2.PdfReader", return_value=reader):
            with patch("app.connectors.file_upload.FileUploadConnector._read_minio",
                       return_value=io.BytesIO(b"%PDF")):
                docs = await conn.extract()
        assert docs == []


class TestDocxExtraction:
    async def test_docx_extracts_paragraphs(self) -> None:
        conn = _make_connector("uploads/doc.docx")
        para = MagicMock()
        para.text = "A paragraph"
        doc = MagicMock()
        doc.paragraphs = [para]
        with patch("docx.Document", return_value=doc):
            with patch("app.connectors.file_upload.FileUploadConnector._read_minio",
                       return_value=io.BytesIO(b"PK")):
                docs = await conn.extract()
        assert docs[0].content == "A paragraph"


class TestTextExtraction:
    async def test_utf8_text_file(self) -> None:
        conn = _make_connector("uploads/doc.txt")
        content = "Hello UTF-8 World"
        with patch("app.connectors.file_upload.FileUploadConnector._read_minio",
                   return_value=io.BytesIO(content.encode("utf-8"))):
            docs = await conn.extract()
        assert docs[0].content == content

    async def test_latin1_fallback(self) -> None:
        conn = _make_connector("uploads/doc.txt")
        content = "caf\xe9"  # café in latin-1
        with patch("app.connectors.file_upload.FileUploadConnector._read_minio",
                   return_value=io.BytesIO(content.encode("latin-1"))):
            docs = await conn.extract()
        assert "caf" in docs[0].content


class TestSizeLimitEnforcement:
    async def test_rejects_oversized_file(self) -> None:
        limit = 50 * 1024 * 1024  # 50 MB from config
        conn = _make_connector("uploads/huge.pdf", size_bytes=limit + 1)
        with pytest.raises(ValueError, match="exceeds maximum"):
            await conn.extract()
```

---

## File 3 — `tests/unit/connectors/test_database_connector.py`

```python
"""Unit tests for DatabaseConnector (FR-020 log-safety included)."""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.connectors.database import DatabaseConnector


SAFE_CONN = "postgresql+asyncpg://user:secret@db:5432/mydb"
QUERY = "SELECT id, content FROM docs"


def _make_connector(conn: str = SAFE_CONN, query: str = QUERY) -> DatabaseConnector:
    return DatabaseConnector(
        source_id="00000000-0000-0000-0000-000000000003",
        config={"connection_string": conn, "query": query, "page_size": 100},
    )


class TestFR020LogSafety:
    async def test_connection_string_not_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        conn = _make_connector()
        row = MagicMock()
        row._mapping = {"id": 1, "content": "hello"}
        result = MagicMock()
        result.fetchall = MagicMock(return_value=[row])
        result.rowcount = 1

        mock_engine = AsyncMock()
        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = AsyncMock(return_value=result)
        mock_engine.connect.return_value = mock_conn

        with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            with caplog.at_level(logging.DEBUG):
                await conn.extract()

        for record in caplog.records:
            assert SAFE_CONN not in record.message, (
                f"Connection string leaked in log: {record.message!r}"
            )
            assert "secret" not in record.message


class TestPagination:
    async def test_paginates_until_empty(self) -> None:
        conn = _make_connector(query=QUERY)
        batch1 = [MagicMock(_mapping={"id": i, "content": f"row{i}"}) for i in range(100)]
        batch2 = [MagicMock(_mapping={"id": i + 100, "content": f"row{i+100}"}) for i in range(50)]
        batch3 = []

        call_count = 0

        async def fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            r = MagicMock()
            r.fetchall = MagicMock(return_value=[batch1, batch2, batch3][call_count - 1])
            r.rowcount = len([batch1, batch2, batch3][call_count - 1])
            return r

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = fake_execute
        mock_engine = AsyncMock()
        mock_engine.connect.return_value = mock_conn

        with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            docs = await conn.extract()

        assert len(docs) == 150

    async def test_empty_result(self) -> None:
        conn = _make_connector()
        r = MagicMock()
        r.fetchall = MagicMock(return_value=[])

        mock_conn = AsyncMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=False)
        mock_conn.execute = AsyncMock(return_value=r)
        mock_engine = AsyncMock()
        mock_engine.connect.return_value = mock_conn

        with patch("sqlalchemy.ext.asyncio.create_async_engine", return_value=mock_engine):
            docs = await conn.extract()

        assert docs == []
```

---

## File 4 — `tests/unit/connectors/test_connector_factory.py`

```python
"""Unit tests for ConnectorFactory (FR-020 log-safety)."""
from __future__ import annotations

import logging

import pytest

from app.connectors.factory import ConnectorFactory
from app.models.enums import SourceType


class TestFactoryBuild:
    def test_returns_web_url_connector(self) -> None:
        factory = ConnectorFactory()
        c = factory.build(SourceType.WEB_URL, "src-1", {"url": "https://x.com"})
        assert c.__class__.__name__ == "WebUrlConnector"

    def test_returns_file_upload_connector(self) -> None:
        factory = ConnectorFactory()
        c = factory.build(SourceType.FILE_UPLOAD, "src-2",
                          {"storage_path": "uploads/f.pdf", "file_size_bytes": 1024})
        assert c.__class__.__name__ == "FileUploadConnector"

    def test_returns_database_connector(self) -> None:
        factory = ConnectorFactory()
        c = factory.build(SourceType.DATABASE, "src-3",
                          {"connection_string": "postgresql://u:p@db/n", "query": "SELECT 1"})
        assert c.__class__.__name__ == "DatabaseConnector"

    def test_unknown_type_raises_key_error(self) -> None:
        factory = ConnectorFactory()
        with pytest.raises(KeyError):
            factory.build("UNKNOWN_TYPE", "src-4", {})  # type: ignore[arg-type]


class TestFactoryFR020:
    def test_connection_string_not_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        factory = ConnectorFactory()
        secret_conn = "postgresql+asyncpg://admin:TOP_SECRET@db:5432/prod"
        with caplog.at_level(logging.DEBUG):
            factory.build(SourceType.DATABASE, "src-5",
                          {"connection_string": secret_conn, "query": "SELECT 1"})
        for record in caplog.records:
            assert secret_conn not in record.message, (
                f"Connection string leaked: {record.message!r}"
            )
            assert "TOP_SECRET" not in record.message
```

---

## Acceptance Criteria

1. `test_web_url_connector.py` — 9 test cases pass; robots.txt allow/disallow paths covered.
2. `test_file_upload_connector.py` — PDF, DOCX, UTF-8 text, latin-1 fallback, size-limit rejection.
3. `test_database_connector.py` — FR-020 log-safety assertion explicitly verifies `connection_string` absent; pagination (100+50+0 batches) verified.
4. `test_connector_factory.py` — `WEB_URL`, `FILE_UPLOAD`, `DATABASE` build correctly; unknown type raises `KeyError`; FR-020 log check passes.
5. All tests use `asyncio_mode=auto` (no explicit `@pytest.mark.asyncio`).
6. All tests run without real HTTP, DB, or MinIO connections (fully mocked).
7. Coverage for `app/connectors/` ≥ 80 % after this task.
