"""MinIO storage service — raw object upload/download (T-046)."""
from __future__ import annotations

import io
import logging
from typing import Any

from minio import Minio  # type: ignore[import-untyped]

from src.core.config import Settings

logger = logging.getLogger(__name__)


class StorageService:
    """Thin wrapper around the MinIO client for raw-object operations."""

    def __init__(self, settings: Settings | None = None) -> None:
        if settings is None:
            from src.core.config import settings as _default_settings  # noqa: PLC0415

            settings = _default_settings
        self._settings = settings
        self._client: Minio = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        self._bucket = settings.MINIO_BUCKET

    # ------------------------------------------------------------------ #
    # Public helpers
    # ------------------------------------------------------------------ #

    async def upload_bytes(
        self,
        data: bytes,
        object_key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload *data* to MinIO under *object_key*.

        Returns the object key on success.
        Raises on MinIO error (caller decides how to handle).
        """
        # minio-py is synchronous — run in the calling coroutine (blocking).
        # A future task may move this to run_in_executor; sufficient for now.
        self._client.put_object(
            bucket_name=self._bucket,
            object_name=object_key,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        logger.info("StorageService: uploaded %d bytes to %s", len(data), object_key)
        return object_key

    async def download_bytes(self, object_key: str) -> bytes:
        """Download and return raw bytes for *object_key*."""
        response: Any = self._client.get_object(
            bucket_name=self._bucket,
            object_name=object_key,
        )
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
