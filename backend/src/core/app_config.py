"""Application-level configuration loaded from app_config.yaml (T-047).

This module provides a typed, cached view of the non-secret configuration
stored in ``backend/src/config/app_config.yaml``.  Secrets (DB URL, MinIO
credentials, etc.) live in ``.env`` and are handled by
:class:`src.core.config.Settings`.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Resolved once at module import time so that lru_cache returns the correct
# path even if the working directory changes between calls.
_CONFIG_PATH: Path = Path(__file__).parent.parent / "config" / "app_config.yaml"


# ---------------------------------------------------------------------------
# Nested config models
# ---------------------------------------------------------------------------


class FileUploadConfig(BaseModel):
    """Configuration for file-upload ingestion."""

    max_size_bytes: int = Field(
        default=52_428_800,  # 50 MiB
        description="Maximum allowed upload size in bytes.",
    )
    supported_formats: list[str] = Field(
        default_factory=lambda: ["pdf", "docx", "xlsx", "csv", "txt", "md"],
        description="Lower-case file extensions accepted for ingestion.",
    )


class BootstrapConfig(BaseModel):
    """Configuration for first-run bootstrap (admin user seeding)."""

    admin_email_env: str = Field(
        default="BOOTSTRAP_ADMIN_EMAIL",
        description="Name of the env-var that holds the bootstrap admin e-mail.",
    )
    admin_password_env: str = Field(
        default="BOOTSTRAP_ADMIN_PASSWORD",
        description="Name of the env-var that holds the bootstrap admin password.",
    )


# ---------------------------------------------------------------------------
# Root config model
# ---------------------------------------------------------------------------


class AppConfig(BaseModel):
    """Root application configuration, sourced from ``app_config.yaml``."""

    file_upload: FileUploadConfig = Field(default_factory=FileUploadConfig)
    bootstrap: BootstrapConfig = Field(default_factory=BootstrapConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_app_config(path: Path | None = None) -> AppConfig:
    """Return the cached :class:`AppConfig`.

    Parameters
    ----------
    path:
        Override the YAML file path (useful in tests).  Defaults to the
        bundled ``backend/src/config/app_config.yaml``.
    """
    resolved: Path = path if path is not None else _CONFIG_PATH

    raw: dict[str, Any] = {}
    if resolved.exists():
        with resolved.open(encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
            if isinstance(loaded, dict):
                raw = loaded
        logger.debug("AppConfig loaded from %s", resolved)
    else:
        logger.warning(
            "AppConfig file not found at %s — using defaults.",
            resolved,
        )

    return AppConfig.model_validate(raw)
