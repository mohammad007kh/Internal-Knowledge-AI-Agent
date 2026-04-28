"""MinIO storage service — raw object upload/download (T-046)."""
from __future__ import annotations

import asyncio
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
        # Internal client — used for all backend-side operations (bucket
        # bootstrap, server-to-server uploads, downloads).  Reaches MinIO
        # over the Docker network at MINIO_ENDPOINT (e.g. ``minio:9000``).
        self._client: Minio = Minio(
            endpoint=settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        # Signing client — only used to generate presigned URLs that the
        # browser will hit directly.  It must be constructed with the
        # browser-reachable host (MINIO_PUBLIC_ENDPOINT, e.g.
        # ``localhost:9000``) so the SigV4 ``host`` header signed into the
        # URL matches the ``Host`` header the browser actually sends.
        # Otherwise MinIO returns ``403 SignatureDoesNotMatch``.
        #
        # ``region`` is pinned explicitly: when minio-py generates a
        # presigned URL it normally performs a ``GetBucketLocation`` round
        # trip against the configured endpoint to discover the region.
        # The signing endpoint (e.g. ``localhost:9000``) is not reachable
        # from inside the backend container, so we must avoid that lookup
        # by passing the region directly.  ``us-east-1`` is the default
        # MinIO single-site region and matches the credentials used by
        # the internal client.
        public_endpoint = settings.MINIO_PUBLIC_ENDPOINT or settings.MINIO_ENDPOINT
        self._signing_client: Minio = Minio(
            endpoint=public_endpoint,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
            region="us-east-1",
        )
        self._bucket = settings.MINIO_BUCKET
        self._bucket_ensured: bool = False

    # ------------------------------------------------------------------ #
    # Bucket bootstrap
    # ------------------------------------------------------------------ #

    async def _ensure_bucket(self) -> None:
        """Ensure the configured bucket exists; create it if missing.

        Result is cached on the instance so subsequent calls are no-ops.
        Runs the synchronous MinIO calls in a worker thread to avoid
        blocking the event loop.
        """
        if self._bucket_ensured:
            return

        def _check_and_create() -> None:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
                logger.info("StorageService: created bucket %s", self._bucket)

        await asyncio.to_thread(_check_and_create)
        self._bucket_ensured = True

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
        # minio-py is synchronous — offload to a worker thread so the
        # event loop is not blocked on the HTTP round-trip.
        await self._ensure_bucket()
        await asyncio.to_thread(
            self._client.put_object,
            self._bucket,
            object_key,
            io.BytesIO(data),
            len(data),
            content_type,
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
        response: Any = await asyncio.to_thread(
            self._client.get_object,
            bucket_name,
            object_key,
        )
        try:
            return await asyncio.to_thread(response.read)  # type: ignore[no-any-return]
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
        # Make sure the bucket exists before issuing a presigned URL —
        # otherwise the browser PUT would 404 against MinIO.  The check is
        # cheap (single HEAD against MinIO) and runs in a worker thread.
        await self._ensure_bucket()
        # Sign the URL against the *public* endpoint (the host the browser
        # will hit).  Using the internal client and rewriting the host
        # afterwards would invalidate the SigV4 ``host`` header and cause a
        # ``403 SignatureDoesNotMatch``.
        # ``presigned_put_object`` performs a synchronous HTTP round-trip
        # internally (region lookup); offload to a worker thread to keep
        # the event loop free.
        url: str = await asyncio.to_thread(
            self._signing_client.presigned_put_object,
            self._bucket,
            object_key,
            timedelta(minutes=expires_minutes),
        )
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
            await asyncio.to_thread(
                self._client.stat_object,
                bucket_name,
                object_key,
            )
            return True
        except Exception:  # noqa: BLE001
            return False
