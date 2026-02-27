"""FastAPI dependency functions for authentication and authorization.

Provides reusable dependencies that protect routes:

* ``get_current_user`` — validates a Bearer access token, loads the user from
  the database, and raises appropriate HTTP errors when the token is missing,
  invalid, expired, or the user account is deactivated.
* ``require_authenticated`` — convenience alias for ``get_current_user``.
* ``require_role(*roles)`` — factory that wraps ``get_current_user`` and also
  verifies the user has one of the required roles.

These are the **only** places where access tokens are decoded outside of tests.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.exceptions import ForbiddenError, UnauthorizedError
from src.core.security import verify_access_token
from src.models.user import User, UserRole
from src.repositories.user_repository import UserRepository

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate Bearer token, load the user, and enforce account-active check.

    Raises
    ------
    UnauthorizedError (401)
        Token is missing, expired, tampered, or the user does not exist.
    ForbiddenError (403)
        The user account has been deactivated.
    """
    if not credentials:
        raise UnauthorizedError("No Bearer token provided")

    # verify_access_token raises UnauthorizedError on failure.
    payload = verify_access_token(credentials.credentials)

    user_id: str | None = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Token missing subject claim")

    user = await UserRepository(db).get_by_id(UUID(user_id))
    if not user:
        raise UnauthorizedError("User not found")

    if not user.is_active:
        raise ForbiddenError("Account is deactivated")

    return user


# Alias — use when you just need "any authenticated user".
require_authenticated = get_current_user


def require_role(*roles: UserRole):
    """Return a FastAPI dependency that enforces one of *roles*.

    Usage::

        @router.get(
            "/admin-only",
            dependencies=[Depends(require_role(UserRole.admin))],
        )

    Raises
    ------
    ForbiddenError (403)
        The authenticated user's role is not in *roles*.
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
