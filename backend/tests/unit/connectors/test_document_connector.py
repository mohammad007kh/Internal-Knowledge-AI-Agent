"""Unit tests for DocumentConnector — T-090."""

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.document_connector import DocumentConnector
from src.core.exceptions import ValidationError


def _make_connector(max_size_mb: int = 50) -> DocumentConnector:
    # DocumentConnector is NOT a BaseConnector subclass — no config dict
    return DocumentConnector(max_size_mb=max_size_mb)


# ---------------------------------------------------------------------------
# TestValidate
# ---------------------------------------------------------------------------

class TestValidate:
    def test_valid_pdf_file(self):
        """validate_file passes for a small .pdf file."""
        connector = _make_connector()
        connector.validate_file("report.pdf", size_bytes=1024)

    def test_valid_docx_file(self):
        """validate_file passes for a small .docx file."""
        connector = _make_connector()
        connector.validate_file("document.docx", size_bytes=2048)

    def test_unsupported_extension_raises_validation_error(self):
        """validate_file raises ValidationError for unsupported extension."""
        connector = _make_connector()
        with pytest.raises(ValidationError):
            connector.validate_file("archive.zip", size_bytes=1024)

    def test_file_exceeding_size_limit_raises_validation_error(self):
        """validate_file raises ValidationError when file exceeds max_size_mb."""
        connector = _make_connector(max_size_mb=50)
        oversized_bytes = 51 * 1024 * 1024  # 51 MB
        with pytest.raises(ValidationError):
            connector.validate_file("big.pdf", size_bytes=oversized_bytes)

    def test_file_exactly_at_size_limit_passes(self):
        """validate_file passes when file is exactly max_size_mb bytes."""
        connector = _make_connector(max_size_mb=50)
        exact_bytes = 50 * 1024 * 1024  # exactly 50 MB
        connector.validate_file("exact.pdf", size_bytes=exact_bytes)

    def test_unsupported_extension_with_valid_size_raises_validation_error(self):
        """validate_file raises ValidationError for .csv even if size is fine."""
        connector = _make_connector()
        with pytest.raises(ValidationError):
            connector.validate_file("data.csv", size_bytes=512)


# ---------------------------------------------------------------------------
# TestExtractText
# ---------------------------------------------------------------------------

class TestExtractText:
    async def test_extract_text_from_pdf_calls_pdf_helper(self):
        """extract_text for a .pdf file invokes _extract_text_from_pdf."""
        connector = _make_connector()
        content = b"%PDF-1.4 fake pdf content"

        with patch(
            "src.connectors.document_connector._extract_text_from_pdf",
            new=AsyncMock(return_value="pdf text"),
        ) as mock_pdf:
            result = await connector.extract_text("file.pdf", content)

        mock_pdf.assert_called_once_with(content)
        assert result == "pdf text"

    async def test_extract_text_from_docx_calls_docx_helper(self):
        """extract_text for a .docx file invokes _extract_text_from_docx."""
        connector = _make_connector()
        content = b"PK fake docx content"

        with patch(
            "src.connectors.document_connector._extract_text_from_docx",
            new=AsyncMock(return_value="docx text"),
        ) as mock_docx:
            result = await connector.extract_text("report.docx", content)

        mock_docx.assert_called_once_with(content)
        assert result == "docx text"

    async def test_extract_text_unsupported_extension_raises_validation_error(self):
        """extract_text raises ValidationError for a .csv file."""
        connector = _make_connector()

        with pytest.raises(ValidationError):
            await connector.extract_text("data.csv", b"col1,col2\n1,2")
