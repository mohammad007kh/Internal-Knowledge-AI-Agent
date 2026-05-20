"""Pydantic schemas for the Embedder admin API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EmbedderCreate(BaseModel):
    """Body for ``POST /api/v1/admin/embedders``."""

    name: str = Field(..., min_length=1, max_length=150)
    provider: str = Field(..., min_length=1, max_length=64)
    model_id: str = Field(..., min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=4000)
    extra_config: dict[str, Any] = Field(default_factory=dict)
    dimensions: int = Field(..., ge=64, le=4096)
    max_input_tokens: int | None = None
    is_active: bool = False

    @model_validator(mode="after")
    def _reject_unsupported_provider(self) -> EmbedderCreate:
        """Reject providers that have no native embedder offering.

        Defense in depth: ``embedding_service_factory._materialise`` performs
        the same check at runtime to catch any stale rows that bypassed this
        validator (legacy data, manual DB inserts, etc.).
        """
        # Local import avoids a circular dependency at module import time.
        from src.services.provider_catalog import PROVIDERS_WITHOUT_NATIVE_EMBEDDER

        if self.provider in PROVIDERS_WITHOUT_NATIVE_EMBEDDER:
            raise ValueError(
                f"Provider '{self.provider}' does not offer a native embedder."
            )
        return self


class EmbedderUpdate(BaseModel):
    """Body for ``PATCH /api/v1/admin/embedders/{id}``.

    ``dimensions`` is read-only after creation.  ``api_key=None`` preserves
    the existing credential.
    """

    name: str | None = Field(default=None, min_length=1, max_length=150)
    provider: str | None = Field(default=None, min_length=1, max_length=64)
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=4000)
    extra_config: dict[str, Any] | None = None
    max_input_tokens: int | None = None
    is_active: bool | None = None

    model_config = ConfigDict(extra="forbid")


class EmbedderPublic(BaseModel):
    id: uuid.UUID
    name: str
    provider: str
    model_id: str
    base_url: str | None
    extra_config: dict[str, Any]
    dimensions: int
    max_input_tokens: int | None
    is_active: bool
    api_key_set: bool
    api_key_last4: str | None
    last_test_at: datetime | None
    last_test_status: str | None
    last_test_error: str | None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None


class EmbedderList(BaseModel):
    items: list[EmbedderPublic]
    total: int
    limit: int
    offset: int


class EmbedderActivatePreview(BaseModel):
    chunks_to_reembed: int
    estimated_seconds: int
    estimated_api_cost_usd: float


class EmbedderActivateResponse(BaseModel):
    job_id: str
    status: str
