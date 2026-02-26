---
id: T-012
title: JWT Utility — 15-min Access Token + 7-day Rotating httpOnly Refresh Cookie
status: Not Started
created: 2026-02-25
phase: Phase 0 — Foundation
user_story: US3, US6
requirements: []
priority: P1
depends_on: [T-004]
blocks: [T-022, T-025]
estimated_effort: 2h
---

## Goal

Create a standalone JWT utility module that issues, validates, and rotates access tokens (15 min) and refresh tokens (7 days). Refresh tokens are stored in httpOnly, SameSite=Strict cookies and persisted in the database (so they can be revoked). All token operations go through this single utility — no ad-hoc JWT calls anywhere else.

---

## Acceptance Criteria

- [ ] `create_access_token(payload)` → signed JWT valid for `ACCESS_TOKEN_EXPIRE_MINUTES`
- [ ] `create_refresh_token(user_id)` → opaque UUID stored in DB, returned as httpOnly cookie
- [ ] `verify_access_token(token)` → decoded payload or raises `UnauthorizedError`
- [ ] `verify_refresh_token(token, db)` → valid `UserRefreshToken` row or raises `UnauthorizedError`
- [ ] `revoke_refresh_token(token, db)` → marks token as revoked (deleted_at set)
- [ ] `set_refresh_cookie(response, token)` → sets `refresh_token` cookie with correct flags
- [ ] `clear_refresh_cookie(response)` → clears cookie on logout
- [ ] Unit tests cover: expired access token, tampered access token, revoked refresh token, unknown refresh token

---

## Files to Create

| Path | Purpose |
|------|---------|
| `backend/src/core/security.py` | JWT encoding/decoding + cookie helpers |
| `backend/src/models/refresh_token.py` | `UserRefreshToken` ORM model |
| `backend/alembic/versions/0002_user_refresh_tokens.py` | Table migration |
| `backend/tests/unit/test_security.py` | Unit tests for all token operations |

---

## Implementation

### `backend/src/core/security.py`

```python
import uuid
from datetime import datetime, timedelta, timezone
from jose import JWTError, jwt
from fastapi import Response
from src.core.config import settings
from src.core.exceptions import UnauthorizedError

ALGORITHM = "HS256"

def create_access_token(payload: dict) -> str:
    data = payload.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    data.update({"exp": expire, "type": "access"})
    return jwt.encode(data, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)

def verify_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise UnauthorizedError("Invalid token type.")
        return payload
    except JWTError as e:
        raise UnauthorizedError("Token is invalid or expired.") from e

def create_refresh_token() -> str:
    """Returns an opaque UUID string to be stored in the database."""
    return str(uuid.uuid4())

def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        samesite="strict",
        secure=True,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        path="/api/v1/auth",
    )

def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key="refresh_token", path="/api/v1/auth")
```

### `backend/src/models/refresh_token.py`

```python
import uuid
from datetime import datetime
from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from src.models.base import Base, UUIDMixin, TimestampMixin

class UserRefreshToken(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "user_refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token: Mapped[str] = mapped_column(String(36), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True, default=None)
```

### Known edge cases

- Refresh tokens are single-use (rotate on each use): old token revoked, new token issued
- On refresh, if `revoked_at` is set → the account may be compromised → revoke **all** tokens for that user
- Expired refresh tokens (past `expires_at`) are cleaned up by a periodic Celery task (T-061)

---

## Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user) |
| Error Format | RFC 7807 Problem Details — all non-2xx API responses |
| Testing | pytest + httpx · ≥80% coverage |
| Domain Rule | All passwords validated via validate_password_policy() — not relevant here, but token policy is equally strict |

---

## 📝 Completion Log

- [ ] Code implemented
- [ ] Alembic migration generated and applied
- [ ] Unit tests pass (≥90% coverage on security.py)
- [ ] Linter passed
- [ ] Integration verified: login → access token in body, refresh token in cookie
