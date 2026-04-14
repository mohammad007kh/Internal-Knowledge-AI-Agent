"""Repository for refresh-token and password-reset-token data access.

Unlike :class:`BaseRepository`, this repository works with raw session
queries because token operations require hash-based lookups and bulk
revocation patterns that don't map to simple CRUD.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.refresh_token import UserRefreshToken
from src.models.user import PasswordResetToken


def _hash_token(raw: str) -> str:
    """Return the SHA-256 hex digest of a raw token string."""
    return hashlib.sha256(raw.encode()).hexdigest()


class RefreshTokenRepository:
    """Data-access layer for ``user_refresh_tokens`` and ``password_reset_tokens``."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # ------------------------------------------------------------------ #
    # Refresh tokens                                                      #
    # ------------------------------------------------------------------ #

    async def get_valid_by_token(
        self, raw_token: str
    ) -> UserRefreshToken | None:
        """Look up an un-revoked, non-expired refresh token by its raw value."""
        token_hash = _hash_token(raw_token)
        result = await self._db.execute(
            select(UserRefreshToken).where(
                UserRefreshToken.token_hash == token_hash,
                UserRefreshToken.revoked_at.is_(None),
                UserRefreshToken.expires_at > datetime.now(UTC),
            )
        )
        return result.scalar_one_or_none()

    async def create_refresh_token(
        self, user_id: UUID, raw_token: str
    ) -> UserRefreshToken:
        """Store a hashed refresh token with a 7-day TTL."""
        record = UserRefreshToken(
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        self._db.add(record)
        await self._db.flush()
        await self._db.refresh(record)
        return record

    async def revoke(self, token_id: UUID) -> None:
        """Mark a single refresh token as revoked."""
        await self._db.execute(
            update(UserRefreshToken)
            .where(UserRefreshToken.id == token_id)
            .values(revoked_at=datetime.now(UTC))
        )
        await self._db.flush()

    async def revoke_all_for_user(self, user_id: UUID) -> None:
        """Revoke every active refresh token belonging to *user_id*."""
        await self._db.execute(
            update(UserRefreshToken)
            .where(
                UserRefreshToken.user_id == user_id,
                UserRefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        await self._db.flush()

    # ------------------------------------------------------------------ #
    # Password-reset tokens                                               #
    # ------------------------------------------------------------------ #

    async def create_password_reset_token(
        self, user_id: UUID, raw_token: str, expires_at: datetime
    ) -> None:
        """Store a hashed password-reset token, invalidating any prior active one."""
        # Invalidate existing active reset tokens for this user
        await self._db.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
            .values(used_at=datetime.now(UTC))
        )
        record = PasswordResetToken(
            user_id=user_id,
            token_hash=_hash_token(raw_token),
            expires_at=expires_at,
        )
        self._db.add(record)
        await self._db.flush()

    async def get_valid_reset_token(
        self, raw_token: str
    ) -> PasswordResetToken | None:
        """Look up an unused, non-expired password-reset token."""
        token_hash = _hash_token(raw_token)
        result = await self._db.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > datetime.now(UTC),
            )
        )
        return result.scalar_one_or_none()

    async def consume_reset_token(self, token_id: UUID) -> None:
        """Mark a password-reset token as consumed."""
        await self._db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id == token_id)
            .values(used_at=datetime.now(UTC))
        )
        await self._db.flush()
