"""MinIO storage service — raw object upload/download (T-046)."""
from __future__ import annotations

import io
import logging
from datetime import timedelta
from typing import Any

try:
    from minio import Minio  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    Minio = None  # type: ignore[assignment,misc]

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

    async def download_bytes(
        self,
        object_key: str,
        bucket: str | None = None,
    ) -> bytes:
        """Download and return raw bytes for *object_key*.

        Parameters
        ----------
        object_key:
            Object name / path inside the bucket.
        bucket:
            Bucket name.  Falls back to the instance default when *None*.
        """
        bucket_name = bucket if bucket is not None else self._bucket
        response: Any = self._client.get_object(
            bucket_name=bucket_name,
            object_name=object_key,
        )
        try:
            return response.read()  # type: ignore[no-any-return]
        finally:
            response.close()
            response.release_conn()

    async def generate_presigned_put_url(
        self,
        object_key: str,
        content_type: str,
        expires_minutes: int = 15,
    ) -> str:
        """Return a presigned PUT URL for direct browser-to-MinIO upload.

        The caller uses the returned URL to ``PUT`` raw bytes directly to
        MinIO without relaying them through the API.  ``content_type`` is
        accepted for symmetry with the upload flow (browsers set the
        ``Content-Type`` header themselves); it is not bound into the URL
        because MinIO's presigned PUT does not pin it by default.

        ``expires_minutes`` is clamped to the inclusive range [1, 15] to
        keep presigned credentials short-lived.
        """
        if expires_minutes > 15:
            raise ValueError("Presigned URL TTL must not exceed 15 minutes")
        if expires_minutes < 1:
            raise ValueError("Presigned URL TTL must be at least 1 minute")
        del content_type  # noqa: F841 - accepted for caller symmetry
        url: str = self._client.presigned_put_object(
            bucket_name=self._bucket,
            object_name=object_key,
            expires=timedelta(minutes=expires_minutes),
        )
        # Rewrite the internal MinIO host (e.g. `minio:9000` inside Docker)
        # with the browser-reachable public host (e.g. `localhost:9000`) so
        # the presigned URL works from the user's browser.
        internal = self._settings.MINIO_ENDPOINT
        public = self._settings.MINIO_PUBLIC_ENDPOINT
        if internal and public and internal != public:
            url = url.replace(internal, public, 1)
        return url

    async def object_exists(
        self,
        object_key: str,
        bucket: str | None = None,
    ) -> bool:
        """Return *True* when *object_key* exists in the bucket.

        Uses ``stat_object`` under the hood; any exception (including
        ``S3Error`` for a missing object) is caught and returns *False* so
        callers can treat this as a simple boolean probe.

        Parameters
        ----------
        object_key:
            Object name / path inside the bucket.
        bucket:
            Bucket name.  Falls back to the instance default when *None*.
        """
        bucket_name = bucket if bucket is not None else self._bucket
        try:
            self._client.stat_object(
                bucket_name=bucket_name,
                object_name=object_key,
            )
            return True
        except Exception:  # noqa: BLE001
            return False
