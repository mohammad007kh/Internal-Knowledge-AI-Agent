"""Unit tests for :pymod:`src.services.user_service` (T-023).

All repository / password interactions are **mocked** so these tests
exercise only the business-logic layer.

Test matrix
~~~~~~~~~~~

register
    - happy path → creates user
    - duplicate email → ConflictError
    - weak password → ValueError (propagated from PasswordService)

invite
    - happy path → creates invitation
    - non-admin caller → ForbiddenError
    - email already registered → ConflictError

accept_invitation
    - happy path → creates user + marks accepted
    - unknown token → NotFoundError
    - already-used token → ConflictError
    - expired token → ValidationError
    - weak password → ValueError

deactivate_user
    - happy path → delegates to repo
    - non-admin caller → ForbiddenError

list_users
    - happy path → returns list
    - non-admin caller → ForbiddenError
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from src.models.user import UserRole
from src.services.user_service import INVITATION_EXPIRY_DAYS, UserService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_PASSWORD = "Str0ng!Pass"


def _make_user(
    *,
    role: UserRole = UserRole.user,
    email: str = "alice@example.com",
    is_active: bool = True,
) -> SimpleNamespace:
    """Lightweight stand-in for a ``User`` ORM instance."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        email=email,
        full_name="Alice",
        role=role,
        is_active=is_active,
        hashed_password="$2b$12$fakehash",
    )


def _make_invitation(
    *,
    token: str = "tok-1234",
    accepted_at: datetime | None = None,
    expired: bool = False,
) -> SimpleNamespace:
    """Lightweight stand-in for an ``Invitation`` ORM instance."""
    if expired:
        expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    else:
        expires_at = datetime.now(timezone.utc) + timedelta(days=INVITATION_EXPIRY_DAYS)

    return SimpleNamespace(
        id=uuid.uuid4(),
        email="bob@example.com",
        token=token,
        role=UserRole.user,
        invited_by=uuid.uuid4(),
        expires_at=expires_at,
        accepted_at=accepted_at,
    )


@pytest.fixture()
def mocks():
    """Return a 5-tuple of
    (user_repo, invitation_repo, password_service,
     refresh_token_repo, email_service)
    wired with sensible async defaults."""
    user_repo = MagicMock()
    user_repo.get_by_email = AsyncMock(return_value=None)
    user_repo.create = AsyncMock(side_effect=lambda **kw: SimpleNamespace(**kw, id=uuid.uuid4()))
    user_repo.set_active = AsyncMock(return_value=None)
    user_repo.list_active = AsyncMock(return_value=[])
    user_repo.count_active = AsyncMock(return_value=0)

    inv_repo = MagicMock()
    inv_repo.get_by_token = AsyncMock(return_value=None)
    inv_repo.create = AsyncMock(side_effect=lambda **kw: SimpleNamespace(**kw, id=uuid.uuid4()))
    inv_repo.mark_accepted = AsyncMock(return_value=None)
    inv_repo.get_pending_by_email = AsyncMock(return_value=None)

    pw_svc = MagicMock()
    pw_svc.validate_password_policy = MagicMock(return_value=None)  # no-op by default
    pw_svc.hash_password = MagicMock(return_value="$2b$12$hashed_value_here")

    refresh_repo = MagicMock()
    refresh_repo.revoke_all_for_user = AsyncMock(return_value=None)

    email_svc = MagicMock()
    email_svc.send_invitation = AsyncMock(return_value=None)

    return user_repo, inv_repo, pw_svc, refresh_repo, email_svc


@pytest.fixture()
def service(mocks):
    user_repo, inv_repo, pw_svc, refresh_repo, email_svc = mocks
    return UserService(user_repo, inv_repo, pw_svc, refresh_repo, email_svc)


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


class TestRegister:
    """Tests for ``UserService.register``."""

    @pytest.mark.asyncio
    async def test_happy_path_creates_user(self, service, mocks) -> None:
        user_repo, _, pw_svc, _, _ = mocks
        user = await service.register("Alice@Example.COM", VALID_PASSWORD, "Alice")

        pw_svc.validate_password_policy.assert_called_once_with(VALID_PASSWORD)
        pw_svc.hash_password.assert_called_once_with(VALID_PASSWORD)
        user_repo.get_by_email.assert_awaited_once_with("Alice@Example.COM")
        user_repo.create.assert_awaited_once()
        # email must be lower-cased
        call_kwargs = user_repo.create.call_args.kwargs
        assert call_kwargs["email"] == "alice@example.com"
        assert call_kwargs["role"] == UserRole.user

    @pytest.mark.asyncio
    async def test_duplicate_email_raises_conflict(self, service, mocks) -> None:
        user_repo, _, _, _, _ = mocks
        user_repo.get_by_email.return_value = _make_user()

        with pytest.raises(ConflictError, match="already registered"):
            await service.register("alice@example.com", VALID_PASSWORD, "Alice")

    @pytest.mark.asyncio
    async def test_weak_password_raises_value_error(self, service, mocks) -> None:
        _, _, pw_svc, _, _ = mocks
        pw_svc.validate_password_policy.side_effect = ValueError("too short")

        with pytest.raises(ValueError, match="too short"):
            await service.register("new@example.com", "bad", "New")


# ---------------------------------------------------------------------------
# invite
# ---------------------------------------------------------------------------


class TestInvite:
    """Tests for ``UserService.invite``."""

    @pytest.mark.asyncio
    async def test_happy_path_creates_invitation(self, service, mocks) -> None:
        user_repo, inv_repo, _, _, email_svc = mocks
        admin = _make_user(role=UserRole.admin)

        invitation, raw_token = await service.invite(admin, "newbie@example.com", UserRole.user)

        inv_repo.create.assert_awaited_once()
        call_kwargs = inv_repo.create.call_args.kwargs
        assert call_kwargs["email"] == "newbie@example.com"
        assert call_kwargs["role"] == UserRole.user
        assert call_kwargs["invited_by"] == admin.id
        assert "token" in call_kwargs
        assert "expires_at" in call_kwargs
        assert isinstance(raw_token, str)
        email_svc.send_invitation.assert_awaited_once_with("newbie@example.com", raw_token)

    @pytest.mark.asyncio
    async def test_non_admin_raises_forbidden(self, service) -> None:
        regular = _make_user(role=UserRole.user)

        with pytest.raises(ForbiddenError, match="Only admins"):
            await service.invite(regular, "someone@example.com", UserRole.user)

    @pytest.mark.asyncio
    async def test_existing_email_raises_conflict(self, service, mocks) -> None:
        user_repo, _, _, _, _ = mocks
        admin = _make_user(role=UserRole.admin)
        user_repo.get_by_email.return_value = _make_user(email="existing@example.com")

        with pytest.raises(ConflictError, match="already exists"):
            await service.invite(admin, "existing@example.com", UserRole.user)

    @pytest.mark.asyncio
    async def test_invitation_expiry_is_7_days(self, service, mocks) -> None:
        _, inv_repo, _, _, _ = mocks
        admin = _make_user(role=UserRole.admin)
        before = datetime.now(timezone.utc)

        await service.invite(admin, "invitee@example.com", UserRole.user)

        call_kwargs = inv_repo.create.call_args.kwargs
        expires_at = call_kwargs["expires_at"]
        expected_min = before + timedelta(days=INVITATION_EXPIRY_DAYS)
        # Allow a small window for clock drift during test execution
        assert expires_at >= expected_min - timedelta(seconds=5)


# ---------------------------------------------------------------------------
# accept_invitation
# ---------------------------------------------------------------------------


class TestAcceptInvitation:
    """Tests for ``UserService.accept_invitation``."""

    @pytest.mark.asyncio
    async def test_happy_path_creates_user(self, service, mocks) -> None:
        _, inv_repo, pw_svc, _, _ = mocks
        invitation = _make_invitation(token="valid-tok")
        inv_repo.get_by_token.return_value = invitation

        user = await service.accept_invitation("valid-tok", "Bob", VALID_PASSWORD)

        pw_svc.validate_password_policy.assert_called_once_with(VALID_PASSWORD)
        pw_svc.hash_password.assert_called_once_with(VALID_PASSWORD)
        inv_repo.mark_accepted.assert_awaited_once_with("valid-tok")

    @pytest.mark.asyncio
    async def test_unknown_token_raises_not_found(self, service, mocks) -> None:
        _, inv_repo, _, _, _ = mocks
        inv_repo.get_by_token.return_value = None

        with pytest.raises(NotFoundError, match="not found"):
            await service.accept_invitation("no-such-token", "X", VALID_PASSWORD)

    @pytest.mark.asyncio
    async def test_already_used_raises_conflict(self, service, mocks) -> None:
        _, inv_repo, _, _, _ = mocks
        inv = _make_invitation(accepted_at=datetime.now(timezone.utc))
        inv_repo.get_by_token.return_value = inv

        with pytest.raises(ConflictError, match="already used"):
            await service.accept_invitation(inv.token, "X", VALID_PASSWORD)

    @pytest.mark.asyncio
    async def test_expired_token_raises_validation_error(self, service, mocks) -> None:
        _, inv_repo, _, _, _ = mocks
        inv = _make_invitation(expired=True)
        inv_repo.get_by_token.return_value = inv

        with pytest.raises(ValidationError, match="expired"):
            await service.accept_invitation(inv.token, "X", VALID_PASSWORD)

    @pytest.mark.asyncio
    async def test_weak_password_raises_value_error(self, service, mocks) -> None:
        _, inv_repo, pw_svc, _, _ = mocks
        inv = _make_invitation()
        inv_repo.get_by_token.return_value = inv
        pw_svc.validate_password_policy.side_effect = ValueError("too short")

        with pytest.raises(ValueError, match="too short"):
            await service.accept_invitation(inv.token, "Bob", "bad")


# ---------------------------------------------------------------------------
# deactivate_user
# ---------------------------------------------------------------------------


class TestDeactivateUser:
    """Tests for ``UserService.deactivate_user``."""

    @pytest.mark.asyncio
    async def test_happy_path_delegates_to_repo(self, service, mocks) -> None:
        user_repo, _, _, refresh_repo, _ = mocks
        admin = _make_user(role=UserRole.admin)
        target_id = uuid.uuid4()

        await service.deactivate_user(admin, target_id)

        user_repo.set_active.assert_awaited_once_with(target_id, False)
        refresh_repo.revoke_all_for_user.assert_awaited_once_with(target_id)

    @pytest.mark.asyncio
    async def test_non_admin_raises_forbidden(self, service) -> None:
        regular = _make_user(role=UserRole.user)

        with pytest.raises(ForbiddenError, match="Only admins"):
            await service.deactivate_user(regular, uuid.uuid4())


# ---------------------------------------------------------------------------
# list_users
# ---------------------------------------------------------------------------


class TestListUsers:
    """Tests for ``UserService.list_users``."""

    @pytest.mark.asyncio
    async def test_happy_path_returns_list(self, service, mocks) -> None:
        user_repo, _, _, _, _ = mocks
        users = [_make_user(), _make_user(email="bob@example.com")]
        user_repo.list_active.return_value = users
        user_repo.count_active.return_value = 2
        admin = _make_user(role=UserRole.admin)

        result, total = await service.list_users(admin, limit=10, offset=0)

        assert result == users
        assert total == 2
        user_repo.list_active.assert_awaited_once_with(limit=10, offset=0)
        user_repo.count_active.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_admin_raises_forbidden(self, service) -> None:
        regular = _make_user(role=UserRole.user)

        with pytest.raises(ForbiddenError, match="Only admins"):
            await service.list_users(regular, limit=10, offset=0)
