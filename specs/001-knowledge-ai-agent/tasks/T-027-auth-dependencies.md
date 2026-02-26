# T-027 — FastAPI Auth Dependencies (`get_current_user`, `require_role`)

## Metadata
| Field | Value |
|---|---|
| **ID** | T-027 |
| **Title** | FastAPI Auth Dependencies — `get_current_user` and `require_role` |
| **Phase** | 1 — Authentication & User Management |
| **Domain** | Backend / Auth |
| **Depends on** | T-012, T-023, T-025 |
| **Blocks** | T-026, T-028, T-030, T-053, T-064, T-070 |
| **Est. complexity** | S |

---

## Goal
Create the two reusable FastAPI dependency functions that every protected route uses:
- `get_current_user(token) -> User` — validates the Bearer access token; raises `401` if invalid/expired
- `require_role(*roles) -> Callable[..., User]` — factory that wraps `get_current_user`; raises `403` if role not in `roles`

These are the **only** places where access tokens are decoded outside of tests.

---

## Deliverables

### 1. `app/core/deps.py`
```python
from uuid import UUID
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.jwt import verify_access_token
from app.core.errors import UnauthorizedError, ForbiddenError
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    FastAPI dependency.

    Validates the Bearer access token, loads the user from DB.
    Raises HTTP 401 if token missing/invalid/expired.
    Raises HTTP 403 if user account is deactivated.
    """
    if not credentials:
        raise UnauthorizedError("No Bearer token provided")

    try:
        payload = verify_access_token(credentials.credentials)
    except UnauthorizedError:
        raise

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Token missing subject claim")

    user = await UserRepository(db).get(UUID(user_id))
    if not user:
        raise UnauthorizedError("User not found")

    if not user.is_active:
        raise ForbiddenError("Account is deactivated")

    return user


# Alias — use when you just need "any authenticated user"
require_authenticated = get_current_user


def require_role(*roles: UserRole):
    """
    Dependency factory.

    Usage:
        @router.get("/admin-only", dependencies=[Depends(require_role(UserRole.admin))])

    Raises 403 if the authenticated user's role is not in *roles.
    """
    async def _check(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role not in roles:
            raise ForbiddenError(
                f"Requires role: {', '.join(r.value for r in roles)}"
            )
        return current_user

    return _check
```

---

### 2. `UserRole` enum — must exist in `app/models/user.py` (from T-021)
```python
import enum

class UserRole(str, enum.Enum):
    admin = "admin"
    user = "user"
```
If not already present — add in T-021 model.

---

### 3. Usage examples (for reference in all subsequent route tasks)
```python
from app.core.deps import require_authenticated, require_role
from app.models.user import UserRole

# Any authenticated user
@router.get("/sources", dependencies=[Depends(require_authenticated)])
async def list_sources(...): ...

# Admin only
@router.delete("/users/{user_id}", dependencies=[Depends(require_role(UserRole.admin))])
async def deactivate_user(...): ...

# Admin only — also capture user object
@router.post("/sources", ...)
async def create_source(
    ...,
    current_user: User = Depends(require_role(UserRole.admin)),
): ...
```

---

## Acceptance Criteria
- [ ] `get_current_user` returns `User` for a valid Bearer token whose sub matches an active user
- [ ] `get_current_user` raises `401` (as RFC 7807) for: missing header, expired token, tampered token
- [ ] `get_current_user` raises `403` for a deactivated user with a valid token
- [ ] `require_role(UserRole.admin)` raises `403` when called by a `user`-role account
- [ ] `require_role(UserRole.admin)` passes when called by an `admin`-role account
- [ ] `require_authenticated` is just an alias for `get_current_user` — no additional logic
- [ ] Unit tests cover all raise paths (missing token, expired, deactivated, wrong role)
- [ ] No inline JWT logic — all decoding delegated to `verify_access_token` from T-012

---

## Notes
- `auto_error=False` on `HTTPBearer` allows a custom 401 rather than FastAPI's default 403
- The DB load ensures the user still exists and hasn't been deactivated after the token was issued
- `require_role` is a **factory** that returns a dependency callable — not a dependency itself
