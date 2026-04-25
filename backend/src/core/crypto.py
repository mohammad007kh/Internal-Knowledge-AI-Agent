"""Shared Fernet encryption helper for symmetric secret storage.

Single source of truth for ``encrypt`` / ``decrypt`` against
``settings.ENCRYPTION_KEY``.  Used by every service that persists API keys
or other secrets at rest (AI models, embedders, source connector configs).

Replaces the no-op stub in ``services/llm_config_service.py`` that
historically wrote API keys as plaintext bytes.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from src.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """Return a cached :class:`Fernet` instance built from ``ENCRYPTION_KEY``.

    The key is expected to be a 32-byte url-safe base64-encoded string, the
    same shape used by :class:`SourceService` and :class:`ConnectorService`.
    """
    return Fernet(settings.ENCRYPTION_KEY.encode())


def encrypt(plain: str) -> bytes:
    """Encrypt *plain* with the project Fernet key.

    Args:
        plain: UTF-8 string to encrypt (must not be ``None``).

    Returns:
        Fernet ciphertext bytes suitable for storage in a ``BYTEA`` column.
    """
    if plain is None:  # type: ignore[unreachable]
        raise ValueError("encrypt() received None — caller must guard")
    return _fernet().encrypt(plain.encode("utf-8"))


def decrypt(blob: bytes) -> str:
    """Decrypt Fernet *blob* and return the original UTF-8 string.

    Args:
        blob: Ciphertext previously produced by :func:`encrypt`.

    Raises:
        cryptography.fernet.InvalidToken: When *blob* was not produced by
            this key (e.g. legacy plaintext or tampered ciphertext).
    """
    return _fernet().decrypt(blob).decode("utf-8")


def try_decrypt(blob: bytes) -> str | None:
    """Best-effort decrypt — returns ``None`` on :class:`InvalidToken`.

    Useful for migration code that needs to detect legacy plaintext rows.
    """
    try:
        return decrypt(blob)
    except InvalidToken:
        return None


def last4(plain: str | None) -> str | None:
    """Return the last 4 characters of *plain* for UX hints, or ``None``."""
    if not plain:
        return None
    if len(plain) < 4:
        return plain
    return plain[-4:]
