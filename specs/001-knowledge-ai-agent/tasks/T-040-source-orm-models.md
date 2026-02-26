# T-040 — Source ORM Models + Migration 0005

## Context
```
Python 3.12 | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector
PostgreSQL 16 + pgvector · UUID PKs · soft-delete + audit columns · Alembic versioned migrations
Fernet (connection configs at rest)
```

## Goal
Define the `Source` ORM model and `SourceType` enum, then generate Alembic migration `0005_sources`.

---

## File 1 — `app/models/enums.py` (extend existing or create)

```python
import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class SourceType(str, enum.Enum):
    WEB_URL = "web_url"
    FILE_UPLOAD = "file_upload"
    DATABASE = "database"
    CONFLUENCE = "confluence"
    SHAREPOINT = "sharepoint"
```

---

## File 2 — `app/models/source.py`

```python
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import BYTEA, UUID
from sqlalchemy.orm import relationship

from app.db.base import Base
from app.models.enums import SourceType
from app.models.mixins import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.user import User


class Source(UUIDMixin, TimestampMixin, Base):
    """Represents a data source configured by an admin."""

    __tablename__ = "sources"

    name: str = Column(String(255), nullable=False, index=True)
    source_type: SourceType = Column(
        Enum(SourceType, name="sourcetype", create_constraint=True),
        nullable=False,
    )
    # Fernet-encrypted JSON blob: {"url": ..., "credentials": ...}
    # NEVER exposed to unprivileged users or API responses.
    config_encrypted: bytes | None = Column(BYTEA, nullable=True)

    owner_id: uuid.UUID = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_active: bool = Column(Boolean, nullable=False, default=True)

    # ------------------------------------------------------------------ #
    # Relationships
    # ------------------------------------------------------------------ #
    owner: User = relationship("User", back_populates="sources", lazy="selectin")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Source id={self.id} name={self.name!r} type={self.source_type}>"
```

---

## File 3 — `app/models/user.py` (add back-ref relationship)

Append to the `User` model class body (after existing relationships):

```python
    sources = relationship(
        "Source",
        back_populates="owner",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
```

---

## File 4 — `app/db/base.py` — register models import

Ensure `Source` is imported inside `app/db/base.py` (or wherever all models are imported for Alembic to discover):

```python
# app/db/base.py
from app.models.source import Source  # noqa: F401  # register with metadata
```

---

## File 5 — `alembic/versions/0005_sources.py`

```python
"""0005 sources

Revision ID: 0005
Revises: 0004
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type first
    sourcetype = postgresql.ENUM(
        "web_url",
        "file_upload",
        "database",
        "confluence",
        "sharepoint",
        name="sourcetype",
        create_type=True,
    )
    sourcetype.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum(
                "web_url",
                "file_upload",
                "database",
                "confluence",
                "sharepoint",
                name="sourcetype",
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("config_encrypted", postgresql.BYTEA(), nullable=True),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_index("ix_sources_name", "sources", ["name"])
    op.create_index("ix_sources_owner_id", "sources", ["owner_id"])


def downgrade() -> None:
    op.drop_table("sources")
    op.execute("DROP TYPE IF EXISTS sourcetype")
```

---

## Acceptance Criteria

- [ ] `Source` model imports cleanly with no circular imports
- [ ] `SourceType` enum values match connector registry keys (T-045)
- [ ] `config_encrypted` is BYTEA (not TEXT or JSON) — Fernet output is bytes
- [ ] `alembic upgrade head` applies migration without error
- [ ] `alembic downgrade -1` rolls back cleanly
- [ ] `User.sources` back-ref resolves in pytest
