# T-043 â€” Source Pydantic Schemas

**Status:** Done

## Context
```
Python 3.12 | Pydantic v2 Â· FastAPI Â· RFC 7807
FR-020: config_encrypted MUST NOT appear in any API response schema
```

## Goal
Define all Pydantic v2 schemas for the Source domain: create, update, and response shapes. The `config` dict is accepted on input but the encrypted version is **never** returned.

---

## File â€” `app/schemas/source.py`

```python
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import SourceType


# ------------------------------------------------------------------ #
# Input schemas
# ------------------------------------------------------------------ #

class SourceCreate(BaseModel):
    """
    Payload for POST /sources.
    `config` holds credentials/URLs â€” service will Fernet-encrypt before persist.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable source name, unique per owner.",
    )
    source_type: SourceType = Field(
        ...,
        description="Connector type identifier.",
    )
    config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Connection configuration (credentials, URLs, etc.). "
            "Encrypted at rest; never returned in responses."
        ),
    )

    @field_validator("name")
    @classmethod
    def name_no_leading_trailing_slash(cls, v: str) -> str:
        if "/" in v:
            raise ValueError("Source name must not contain '/'.")
        return v


class SourceUpdate(BaseModel):
    """
    Payload for PATCH /sources/{id}.
    All fields optional; only provided fields are changed.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(
        None,
        min_length=1,
        max_length=255,
    )
    config: dict[str, Any] | None = Field(
        None,
        description="Full replacement of the connection config when provided.",
    )
    is_active: bool | None = None


# ------------------------------------------------------------------ #
# Response schemas â€” NO config_encrypted field intentionally
# ------------------------------------------------------------------ #

class SourceResponse(BaseModel):
    """
    Full source representation returned by the API.
    config_encrypted is deliberately absent (FR-020).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: SourceType
    owner_id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SourceListItem(BaseModel):
    """Slim representation used inside paginated lists."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source_type: SourceType
    is_active: bool
    created_at: datetime


class PaginatedSources(BaseModel):
    """Envelope for paginated source lists."""

    items: list[SourceListItem]
    total: int
    limit: int
    offset: int


class TestConnectionResponse(BaseModel):
    """Result of POST /sources/{id}/test-connection."""

    success: bool
    message: str = ""
```

---

## Enum Reference (`app/models/enums.py` â€” defined in T-040)

```python
class SourceType(str, Enum):
    WEB_URL     = "web_url"
    FILE_UPLOAD = "file_upload"
    DATABASE    = "database"
    CONFLUENCE  = "confluence"
    SHAREPOINT  = "sharepoint"
```

---

## Export â€” `app/schemas/__init__.py`

```python
# append:
from app.schemas.source import (
    PaginatedSources,
    SourceCreate,
    SourceListItem,
    SourceResponse,
    SourceUpdate,
    TestConnectionResponse,
)
```

---

## Acceptance Criteria

- [ ] `SourceResponse` has **no** `config`, `config_encrypted`, or credential-like field
- [ ] `SourceCreate` validates `name` contains no `/`
- [ ] `SourceUpdate` is fully optional (all fields `None` â†’ no-op in service)
- [ ] `PaginatedSources` serialises correctly with `model_validate` on a list of `Source` ORM instances
- [ ] `TestConnectionResponse` can be returned directly from the router handler
- [ ] All schemas importable from `app.schemas.source`
