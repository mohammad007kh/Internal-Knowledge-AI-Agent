"""Pydantic schemas for the AIModel admin API.

Public responses NEVER include the plaintext API key — only ``api_key_last4``
and ``api_key_set`` for UX hints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AIModelCreate(BaseModel):
    """Body for ``POST /api/v1/admin/ai-models``."""

    name: str = Field(..., min_length=1, max_length=150)
    provider: str = Field(..., min_length=1, max_length=64)
    model_id: str = Field(..., min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=4000)
    extra_config: dict[str, Any] = Field(default_factory=dict)
    default_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    default_max_tokens: int = Field(default=2048, gt=0)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class AIModelUpdate(BaseModel):
    """Body for ``PATCH /api/v1/admin/ai-models/{id}``.

    ``api_key`` is tri-state: omitted/``None`` → preserve existing; non-empty
    string → replace.  An explicit empty string clears the credential.
    """

    name: str | None = Field(default=None, min_length=1, max_length=150)
    provider: str | None = Field(default=None, min_length=1, max_length=64)
    model_id: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=4000)
    extra_config: dict[str, Any] | None = None
    default_temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    default_max_tokens: int | None = Field(default=None, gt=0)
    capabilities: dict[str, Any] | None = None
    is_active: bool | None = None

    model_config = ConfigDict(extra="forbid")


class AIModelPublic(BaseModel):
    """GET response model — no plaintext key, ever."""

    id: uuid.UUID
    name: str
    provider: str
    model_id: str
    base_url: str | None
    extra_config: dict[str, Any]
    default_temperature: float
    default_max_tokens: int
    capabilities: dict[str, Any]
    is_active: bool
    api_key_set: bool
    api_key_last4: str | None
    last_test_at: datetime | None
    last_test_status: str | None
    last_test_error: str | None
    created_at: datetime
    updated_at: datetime
    created_by: uuid.UUID | None


class AIModelList(BaseModel):
    items: list[AIModelPublic]
    total: int
    limit: int
    offset: int


class TestConnectionPlaintextRequest(BaseModel):
    """Body for ``POST /ai-models/test-connection`` (does not persist)."""

    provider: str
    model_id: str
    api_key: str
    base_url: str | None = None
    extra_config: dict[str, Any] = Field(default_factory=dict)


class TestConnectionResult(BaseModel):
    ok: bool
    latency_ms: int
    error: str | None = None


class AIModelUsage(BaseModel):
    """Response for ``GET /ai-models/{id}/usage``."""

    stages: list[str]
    chat_messages_count: int


class AIModelDeleteConflict(BaseModel):
    error: Literal["referenced"] = "referenced"
    referenced_by: dict[str, Any]
