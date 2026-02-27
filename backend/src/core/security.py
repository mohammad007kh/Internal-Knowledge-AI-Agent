"""JWT utilities and HTTP-only refresh-cookie helpers.

Access tokens
-------------
- Algorithm : HS256
- Lifetime  : ``settings.ACCESS_TOKEN_EXPIRE_MINUTES`` (default 15 min)
- Payload   : arbitrary caller-supplied claims + ``exp`` + ``type="access"``

Refresh tokens
--------------
- Format    : opaque UUID-4 string stored in the ``user_refresh_tokens`` table
- Lifetime  : ``settings.REFRESH_TOKEN_EXPIRE_DAYS`` (default 7 days)
- Transport : httpOnly, Strict SameSite, Secure cookie on path /api/v1/auth
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Response
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.exceptions import UnauthorizedError

ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Access token
# ---------------------------------------------------------------------------


def create_access_token(payload: dict) -> str:
    """Encode *payload* as a signed JWT access token.

    Parameters
    ----------
    payload:
        Arbitrary claims dict.  ``exp`` and ``type`` are added automatically.

    Returns
    -------
    str
        Signed JWT string.
    """
    data = payload.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    data.update({"exp": expire, "type": "access"})
    return jwt.encode(data, settings.JWT_SECRET_KEY, algorithm=ALGORITHM)


def verify_access_token(token: str) -> dict:
    """Decode and validate a JWT access token.

    Parameters
    ----------
    token:
        Raw JWT string from the ``Authorization: Bearer …`` header.

    Returns
    -------
    dict
        Decoded payload.

    Raises
    ------
    UnauthorizedError
        If the token is expired, tampered with, or has the wrong ``type``.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            raise UnauthorizedError("Invalid token type.")
        return payload
    except JWTError as e:
        raise UnauthorizedError("Token is invalid or expired.") from e


# ---------------------------------------------------------------------------
# Refresh token (opaque UUID stored in DB)
# ---------------------------------------------------------------------------


def create_refresh_token() -> str:
    """Return a new opaque UUID-4 string to be persisted in the database."""
    return str(uuid.uuid4())


async def verify_refresh_token(token: str, db: AsyncSession):
    """Look up *token* in the database and validate it.

    Parameters
    ----------
    token:
        Opaque UUID string from the ``refresh_token`` cookie.
    db:
        Active async database session.

    Returns
    -------
    UserRefreshToken
        The ORM row for the valid token.

    Raises
    ------
    UnauthorizedError
        If the token does not exist, has been revoked, or has expired.
    """
    from sqlalchemy import select

    from src.models.refresh_token import UserRefreshToken

    result = await db.execute(
        select(UserRefreshToken).where(UserRefreshToken.token_hash == token)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise UnauthorizedError("Refresh token not found.")
    if row.revoked_at is not None:
        raise UnauthorizedError("Refresh token has been revoked.")
    if row.expires_at < datetime.now(timezone.utc):
        raise UnauthorizedError("Refresh token has expired.")
    return row


async def revoke_refresh_token(token: str, db: AsyncSession) -> None:
    """Mark *token* as revoked by setting ``revoked_at`` to the current UTC time.

    Parameters
    ----------
    token:
        Opaque UUID string to revoke.
    db:
        Active async database session.  Caller is responsible for committing.
    """
    from sqlalchemy import select

    from src.models.refresh_token import UserRefreshToken

    result = await db.execute(
        select(UserRefreshToken).where(UserRefreshToken.token_hash == token)
    )
    row = result.scalar_one_or_none()
    if row is not None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.flush()


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------


def set_refresh_cookie(response: Response, token: str) -> None:
    """Attach an httpOnly refresh-token cookie to *response*.

    Cookie attributes
    -----------------
    httponly : True  — inaccessible to JavaScript
    samesite : "strict"
    secure   : True  — HTTPS only
    path     : /api/v1/auth  — limits exposure to auth endpoints
    max_age  : ``REFRESH_TOKEN_EXPIRE_DAYS`` days in seconds
    """
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
    """Delete the ``refresh_token`` cookie from *response*."""
    response.delete_cookie(key="refresh_token", path="/api/v1/auth")
