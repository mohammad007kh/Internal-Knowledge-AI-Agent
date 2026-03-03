# T-047 â€” File Upload Connector

**Status:** Done

## Context
```
Python 3.12 | MinIO Â· PyPDF2 Â· python-docx Â· pydantic_settings
SourceType.FILE_UPLOAD Â· @register decorator Â· BaseConnector ABC
FR-035: file size limit from app_config.yaml (default 50 MB)
FR-020: connection strings/keys must never appear in user-facing output
```

## Goal
Implement `FileUploadConnector`: retrieve a file already uploaded to MinIO, validate its size, parse text by type (PDF / DOCX / TXT), and yield a single `Document` with `raw_storage_path` set to the original MinIO object key.

---

## File â€” `app/connectors/file_upload_connector.py`

```python
from __future__ import annotations

import io
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.connectors.base import BaseConnector, Document
from app.connectors.registry import register
from app.core.app_config import get_app_config
from app.models.enums import SourceType
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)

_SUPPORTED_TYPES = {"pdf", "docx", "txt"}
_BYTES_PER_MB = 1024 * 1024


@register(SourceType.FILE_UPLOAD)
class FileUploadConnector(BaseConnector):
    """
    Connector for files already stored in MinIO.

    Expected *config* keys:
        minio_bucket (str, required)  â€” MinIO bucket name
        object_key   (str, required)  â€” full object path inside the bucket
        file_type    (str, required)  â€” one of: pdf | docx | txt

    source_id must also be present in config (injected by ConnectorFactory in T-050).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._bucket: str = config["minio_bucket"]
        self._object_key: str = config["object_key"]
        self._file_type: str = config["file_type"].lower()
        self._storage: StorageService = StorageService()
        self._raw_data: bytes | None = None  # loaded in connect()

        if self._file_type not in _SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported file_type '{self._file_type}'. "
                f"Supported types: {sorted(_SUPPORTED_TYPES)}"
            )

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        """
        Download the file from MinIO and validate size against app_config.
        Raises ValueError if the file exceeds the configured limit.
        """
        app_config = get_app_config()
        max_mb: float = float(
            getattr(app_config.files, "max_size_mb", 50)
        )
        max_bytes = int(max_mb * _BYTES_PER_MB)

        logger.info(
            "FileUploadConnector: downloading object_key=%s from bucket=%s",
            self._object_key,
            self._bucket,
        )

        raw_data = await self._storage.download_bytes(
            bucket=self._bucket,
            object_key=self._object_key,
        )

        if len(raw_data) > max_bytes:
            raise ValueError(
                f"File exceeds configured limit of {max_mb} MB "
                f"(actual: {len(raw_data) / _BYTES_PER_MB:.2f} MB)."
            )

        self._raw_data = raw_data
        logger.info(
            "FileUploadConnector: downloaded %d bytes for object_key=%s",
            len(raw_data),
            self._object_key,
        )

    async def disconnect(self) -> None:
        self._raw_data = None
        logger.info("FileUploadConnector: released in-memory data")

    # ------------------------------------------------------------------ #
    # Parsers (private)
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_pdf(data: bytes) -> str:
        try:
            import PyPDF2  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError("PyPDF2 is required for PDF parsing") from exc

        reader = PyPDF2.PdfReader(io.BytesIO(data))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages.append(text)
        return "\n\n".join(pages)

    @staticmethod
    def _parse_docx(data: bytes) -> str:
        try:
            import docx  # python-docx  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError("python-docx is required for DOCX parsing") from exc

        doc = docx.Document(io.BytesIO(data))
        return "\n".join(para.text for para in doc.paragraphs if para.text)

    @staticmethod
    def _parse_txt(data: bytes) -> str:
        encodings = ("utf-8", "utf-8-sig", "latin-1")
        for enc in encodings:
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        # Last-resort fallback: replace undecodable bytes
        return data.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------ #
    # Extraction
    # ------------------------------------------------------------------ #

    async def extract_documents(self) -> AsyncIterator[Document]:
        assert self._raw_data is not None, (
            "Call connect() before extract_documents()"
        )

        if self._file_type == "pdf":
            raw_text = self._parse_pdf(self._raw_data)
        elif self._file_type == "docx":
            raw_text = self._parse_docx(self._raw_data)
        else:  # txt
            raw_text = self._parse_txt(self._raw_data)

        source_id = self._config.get("source_id", "unknown")

        yield Document(
            source_id=source_id,  # type: ignore[arg-type]
            raw_text=raw_text,
            metadata={
                "object_key": self._object_key,
                "bucket": self._bucket,
                "file_type": self._file_type,
                "size_bytes": len(self._raw_data),
            },
            raw_storage_path=self._object_key,
        )

    # ------------------------------------------------------------------ #
    # test_connection
    # ------------------------------------------------------------------ #

    async def test_connection(self) -> bool:
        """
        Verify that the object exists in MinIO via stat.
        Returns False (not raises) on any failure.
        """
        try:
            exists = await self._storage.object_exists(
                bucket=self._bucket,
                object_key=self._object_key,
            )
            return exists
        except Exception as exc:
            logger.warning("FileUploadConnector.test_connection failed: %s", exc)
            return False
```

---

## `app/services/storage_service.py` â€” additions required

Add `download_bytes` and `object_exists` if not already present:

```python
async def download_bytes(self, bucket: str, object_key: str) -> bytes:
    """Download object from MinIO and return raw bytes. Raises on error."""
    import io
    response = self._client.get_object(bucket_name=bucket, object_name=object_key)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()

async def object_exists(self, bucket: str, object_key: str) -> bool:
    """Return True if the object exists; False otherwise (never raises)."""
    try:
        self._client.stat_object(bucket_name=bucket, object_name=object_key)
        return True
    except Exception:
        return False
```

---

## `app/core/app_config.py` â€” relevant section

```python
# app_config.yaml structure (relevant excerpt):
# files:
#   max_size_mb: 50

from functools import lru_cache
import yaml
from pydantic import BaseModel


class FilesConfig(BaseModel):
    max_size_mb: float = 50.0


class AppConfig(BaseModel):
    files: FilesConfig = FilesConfig()


@lru_cache(maxsize=1)
def get_app_config() -> AppConfig:
    try:
        with open("app_config.yaml") as fh:
            raw = yaml.safe_load(fh) or {}
    except FileNotFoundError:
        raw = {}
    return AppConfig.model_validate(raw)
```

---

## `requirements.txt` additions

```
PyPDF2>=3.0.0
python-docx>=1.1.0
```

---

## Acceptance Criteria

- [ ] `FileUploadConnector` is auto-registered for `SourceType.FILE_UPLOAD` via `@register`
- [ ] `__init__` raises `ValueError` immediately for unsupported `file_type` values
- [ ] `connect()` downloads from MinIO and raises `ValueError` when file exceeds `app_config.yaml` `files.max_size_mb` (default 50 MB)
- [ ] `extract_documents()` yields exactly one `Document`; `raw_storage_path` equals the MinIO `object_key`
- [ ] PDF parsing uses PyPDF2; DOCX uses python-docx; TXT tries UTF-8 then latin-1 before falling back to replace-errors
- [ ] `disconnect()` clears `_raw_data` from memory
- [ ] `test_connection()` calls `storage.object_exists()` and returns `False` (not raises) on any exception
- [ ] `object_key` and `bucket` appear only in `metadata` field of `Document`, never in log WARNING/ERROR messages at URL detail level
