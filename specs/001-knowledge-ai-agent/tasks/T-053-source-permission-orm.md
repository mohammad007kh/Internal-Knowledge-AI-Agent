# T-053 — SourcePermission ORM Model & Migration

## Context
```
Python 3.12 | SQLAlchemy 2.x (async) · Pydantic v2
PostgreSQL 16 · UUID PKs · Alembic versioned migrations
Multi-tenant source access control (FR-019)
```

## Goal
Create the `source_permissions` join table that controls which users may access
which sources inside the AI pipeline (FR-019: "Source access is per-user per-source;
never expose unapproved source data").

---

## File 1 — `app/models/source_permission.py`

```python
"""SourcePermission join model — governs which user can access which source."""
from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base_class import Base
from app.models.mixins import TimestampMixin, UUIDMixin


class SourcePermission(UUIDMixin, TimestampMixin, Base):
    """
    Explicit allow-list table.  An admin (owner of the source) grants
    access to individual users.  The AI retrieval pipeline filters
    `Chunk.source_id` to the set of source IDs the requesting user has
    a matching row here (or owns directly).

    Notes
    -----
    - Hard-deleted (no soft-delete) — revocation is immediate.
    - `UniqueConstraint(source_id, user_id)` prevents duplicate grants.
    - Cascade on both parent FKs so rows are removed when a source or
      user is deleted.
    """

    __tablename__ = "source_permissions"
    __table_args__ = (
        UniqueConstraint("source_id", "user_id", name="uq_source_permissions"),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # Relationships (lazy="raise" — always use explicit joins or services)
    # ------------------------------------------------------------------
    source: Mapped["Source"] = relationship(  # noqa: F821
        "Source",
        back_populates="permissions",
        lazy="raise",
    )
    user: Mapped["User"] = relationship(  # noqa: F821
        "User",
        back_populates="source_permissions",
        lazy="raise",
    )
```

---

## File 2 — `app/models/source.py` (patch — add `permissions` relationship)

```python
# Inside Source class, before the closing `__repr__`:
permissions: Mapped[list["SourcePermission"]] = relationship(
    "SourcePermission",
    back_populates="source",
    cascade="all, delete-orphan",
    lazy="raise",
)
```

---

## File 3 — `app/models/user.py` (patch — add `source_permissions` relationship)

```python
# Inside User class:
source_permissions: Mapped[list["SourcePermission"]] = relationship(
    "SourcePermission",
    back_populates="user",
    cascade="all, delete-orphan",
    lazy="raise",
)
```

---

## File 4 — `app/db/base.py` (patch — register model for Alembic)

```python
from app.models.source_permission import SourcePermission  # noqa: F401
```

---

## File 5 — `alembic/versions/0007_source_permissions.py`

```python
"""source_permissions table

Revision ID: 0007
Revises: 0006
Create Date: 2025-01-01 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_permissions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("source_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
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
            onupdate=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "source_id", "user_id", name="uq_source_permissions"
        ),
    )
    op.create_index(
        "ix_source_permissions_source_id",
        "source_permissions",
        ["source_id"],
    )
    op.create_index(
        "ix_source_permissions_user_id",
        "source_permissions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_permissions_user_id", table_name="source_permissions")
    op.drop_index("ix_source_permissions_source_id", table_name="source_permissions")
    op.drop_table("source_permissions")
```

---

## Acceptance Criteria

1. `SourcePermission` imports cleanly from `app.models.source_permission`.
2. The `UniqueConstraint("source_id", "user_id")` is present in `__table_args__`.
3. Both FKs have `ondelete="CASCADE"`.
4. `Source.permissions` and `User.source_permissions` back-references are wired.
5. `app/db/base.py` imports `SourcePermission` for Alembic autogenerate.
6. Migration `0007` creates the table, two indexes, unique constraint, and both FKs.
7. `downgrade()` reverses all DDL from `upgrade()`.
