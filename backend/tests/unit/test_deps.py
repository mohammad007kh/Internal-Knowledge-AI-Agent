"""Tests for ``src.core.deps`` — auth dependencies.

Covers all AC paths:
- Valid token → User returned
- Missing token → 401
- Invalid/expired/tampered token → 401
- User not found → 401
- Deactivated user → 403
- require_role with wrong role → 403
- require_role with correct role → passes
- require_authenticated is alias
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.deps import get_current_user, require_authenticated, require_role
from src.core.exceptions import ForbiddenError, UnauthorizedError
from src.models.user import User, UserRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    *,
    user_id: uuid.UUID | None = None,
    role: UserRole = UserRole.user,
    is_active: bool = True,
) -> User:
    """Return a User stub with the fields the deps touch."""
    u = MagicMock(spec=User)
    u.id = user_id or uuid.uuid4()
    u.role = role
    u.is_active = is_active
    return u


def _make_credentials(token: str = "valid.jwt.token"):
    cred = MagicMock()
    cred.credentials = token
    return cred


# ---------------------------------------------------------------------------
# get_current_user — happy path
# ---------------------------------------------------------------------------


class TestGetCurrentUserHappy:
    """AC-1: valid Bearer token whose sub matches an active user → User."""

    @pytest.mark.asyncio
    async def test_returns_user_for_valid_token(self):
        user = _make_user()
        payload = {"sub": str(user.id), "role": user.role.value, "type": "access"}

        mock_repo_instance = AsyncMock()
        mock_repo_instance.get_by_id.return_value = user

        with (
            patch(
                "src.core.deps.verify_access_token", return_value=payload
            ) as mock_verify,
            patch(
                "src.core.deps.UserRepository", return_value=mock_repo_instance
            ),
        ):
            result = await get_current_user(
                credentials=_make_credentials("tok"), db=AsyncMock()
            )

        assert result is user
        mock_verify.assert_called_once_with("tok")
        mock_repo_instance.get_by_id.assert_called_once_with(user.id)


# ---------------------------------------------------------------------------
# get_current_user — 401 paths
# ---------------------------------------------------------------------------


class TestGetCurrentUser401:
    """AC-2: missing header, expired, tampered → 401."""

    @pytest.mark.asyncio
    async def test_missing_credentials_raises_401(self):
        with pytest.raises(UnauthorizedError):
            await get_current_user(credentials=None, db=AsyncMock())

    @pytest.mark.asyncio
    async def test_expired_token_raises_401(self):
        with (
            patch(
                "src.core.deps.verify_access_token",
                side_effect=UnauthorizedError("expired"),
            ),
            pytest.raises(UnauthorizedError),
        ):
            await get_current_user(
                credentials=_make_credentials(), db=AsyncMock()
            )

    @pytest.mark.asyncio
    async def test_tampered_token_raises_401(self):
        with (
            patch(
                "src.core.deps.verify_access_token",
                side_effect=UnauthorizedError("tampered"),
            ),
            pytest.raises(UnauthorizedError),
        ):
            await get_current_user(
                credentials=_make_credentials(), db=AsyncMock()
            )

    @pytest.mark.asyncio
    async def test_missing_sub_claim_raises_401(self):
        payload = {"type": "access"}  # no "sub"
        with (
            patch(
                "src.core.deps.verify_access_token", return_value=payload
            ),
            pytest.raises(UnauthorizedError),
        ):
            await get_current_user(
                credentials=_make_credentials(), db=AsyncMock()
            )

    @pytest.mark.asyncio
    async def test_user_not_found_raises_401(self):
        uid = uuid.uuid4()
        payload = {"sub": str(uid), "type": "access"}
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None

        with (
            patch(
                "src.core.deps.verify_access_token", return_value=payload
            ),
            patch(
                "src.core.deps.UserRepository", return_value=mock_repo
            ),
            pytest.raises(UnauthorizedError),
        ):
            await get_current_user(
                credentials=_make_credentials(), db=AsyncMock()
            )


# ---------------------------------------------------------------------------
# get_current_user — 403 path
# ---------------------------------------------------------------------------


class TestGetCurrentUser403:
    """AC-3: deactivated user with valid token → 403."""

    @pytest.mark.asyncio
    async def test_deactivated_user_raises_403(self):
        user = _make_user(is_active=False)
        payload = {"sub": str(user.id), "type": "access"}
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = user

        with (
            patch(
                "src.core.deps.verify_access_token", return_value=payload
            ),
            patch(
                "src.core.deps.UserRepository", return_value=mock_repo
            ),
            pytest.raises(ForbiddenError),
        ):
            await get_current_user(
                credentials=_make_credentials(), db=AsyncMock()
            )


# ---------------------------------------------------------------------------
# require_role
# ---------------------------------------------------------------------------


class TestRequireRole:
    """AC-4 & AC-5: role enforcement."""

    @pytest.mark.asyncio
    async def test_wrong_role_raises_403(self):
        """AC-4: user-role account calling admin-only → 403."""
        user = _make_user(role=UserRole.user)
        dep = require_role(UserRole.admin)

        with pytest.raises(ForbiddenError):
            await dep(current_user=user)

    @pytest.mark.asyncio
    async def test_correct_role_passes(self):
        """AC-5: admin-role account calling admin-only → allowed."""
        user = _make_user(role=UserRole.admin)
        dep = require_role(UserRole.admin)

        result = await dep(current_user=user)
        assert result is user

    @pytest.mark.asyncio
    async def test_multiple_roles_accepted(self):
        """Either admin or user role is accepted."""
        user = _make_user(role=UserRole.user)
        dep = require_role(UserRole.admin, UserRole.user)

        result = await dep(current_user=user)
        assert result is user


# ---------------------------------------------------------------------------
# require_authenticated alias
# ---------------------------------------------------------------------------


class TestRequireAuthenticated:
    """AC-6: require_authenticated is just an alias for get_current_user."""

    def test_is_same_function(self):
        assert require_authenticated is get_current_user


# ---------------------------------------------------------------------------
# No inline JWT logic (AC-8)
# ---------------------------------------------------------------------------


class TestNoDuplicatedJWTLogic:
    """AC-8: deps.py must not import jose or manually decode tokens."""

    def test_no_jose_import(self):
        import src.core.deps as deps_module
        import inspect

        source = inspect.getsource(deps_module)
        assert "from jose" not in source
        assert "import jose" not in source
        assert "jwt.decode" not in source
