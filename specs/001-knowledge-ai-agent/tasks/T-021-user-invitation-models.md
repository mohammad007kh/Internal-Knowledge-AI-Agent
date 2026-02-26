---
id: T-021
title: User & Invitation ORM Models + Alembic Migration
status: Not Started
created: 2026-02-25
phase: Phase 1 — Auth & User Management
user_story: US1, US3
requirements: [FR-AUTH-1, FR-AUTH-2, FR-AUTH-3]
priority: P1
depends_on: [T-013, T-014]
blocks: [T-022, T-023, T-024, T-025, T-026]
estimated_effort: 2h
---

## Goal

Define `User` and `Invitation` SQLAlchemy ORM models and generate the Alembic migration. These tables are the foundation for all auth and user-management features.

---

## Acceptance Criteria

- [ ] `User` model has: `id`, `email` (unique, indexed), `hashed_password`, `full_name`, `role` (enum: admin/user), `is_active`, `created_at`, `updated_at`, `deleted_at`
- [ ] `Invitation` model has: `id`, `email`, `token` (unique UUID), `invited_by` (FK → users.id), `role`, `expires_at`, `accepted_at`, `created_at`
- [ ] `UserRole` Python Enum exists at `src.models.user.UserRole`
- [ ] Migration file: `0003_add_users_invitations.py` (uses file template from T-014)
- [ ] `User` extends `UUIDMixin`, `TimestampMixin`, `SoftDeleteMixin`
- [ ] `Invitation` extends `UUIDMixin`, `TimestampMixin` only (no soft delete—accepted/expired tokens are kept for audit)
- [ ] Unit tests assert round-trip insert + soft delete works

---

## Files to Create

| Path | Purpose |
|------|---------|
| `backend/src/models/user.py` | User + UserRole + Invitation models |
| `backend/alembic/versions/0003_<date>_add_users_invitations.py` | Migration |
| `backend/tests/unit/test_user_models.py` | ORM round-trip tests |

---

## Implementation

### `backend/src/models/user.py`

```python
import enum
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.models.base import Base, UUIDMixin, TimestampMixin, SoftDeleteMixin


class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"


class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(60), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.user)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    refresh_tokens: Mapped[list["UserRefreshToken"]] = relationship(
        "UserRefreshToken", back_populates="user", cascade="all, delete-orphan"
    )
    invitations_sent: Mapped[list["Invitation"]] = relationship(
        "Invitation", back_populates="invited_by_user", foreign_keys="Invitation.invited_by"
    )


class Invitation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(String(254), index=True, nullable=False)
    token: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    invited_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.user)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    invited_by_user: Mapped["User"] = relationship(
        "User", back_populates="invitations_sent", foreign_keys=[invited_by]
    )
```

### Migration checklist

```sql
-- users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(254) UNIQUE NOT NULL,
    hashed_password VARCHAR(60) NOT NULL,
    full_name VARCHAR(200) NOT NULL,
    role user_role NOT NULL DEFAULT 'user',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX ix_users_email ON users (email);

-- invitations table
CREATE TABLE invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(254) NOT NULL,
    token VARCHAR(36) UNIQUE NOT NULL,
    invited_by UUID REFERENCES users(id) ON DELETE SET NULL,
    role user_role NOT NULL DEFAULT 'user',
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

## 📝 Completion Log

- [ ] Models implemented
- [ ] Migration generated (`alembic revision --autogenerate -m "add_users_invitations"`)
- [ ] Migration applied on dev DB
- [ ] `alembic downgrade -1 && alembic upgrade head` roundtrip succeeds
- [ ] Unit tests pass
- [ ] Linter passed
