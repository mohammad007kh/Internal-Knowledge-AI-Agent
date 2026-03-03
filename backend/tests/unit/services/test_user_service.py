"""Unit tests for UserService — T-090."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from src.models.user import UserRole
from src.services.user_service import UserService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user_service(user_repo, invitation_repo=None):
    inv_repo = invitation_repo or AsyncMock()
    return UserService(
        user_repo=user_repo,
        invitation_repo=inv_repo,
        password_service=MagicMock(),
        refresh_token_repo=AsyncMock(),
        email_service=AsyncMock(),
    )


# ---------------------------------------------------------------------------
# TestInviteUser
# ---------------------------------------------------------------------------

class TestInviteUser:
    async def test_new_email_returns_invitation_and_token(self, fake_admin, mock_user_repo):
        """Admin invites a new email → returns (invitation, token) pair."""
        mock_user_repo.get_by_email = AsyncMock(return_value=None)

        invitation_repo = AsyncMock()
        invitation_repo.create = AsyncMock(return_value=MagicMock())

        service = _make_user_service(mock_user_repo, invitation_repo)

        result = await service.invite(
            admin=fake_admin,
            email="newuser@example.com",
            role=UserRole.user,
        )

        assert result is not None

    async def test_duplicate_email_raises_conflict(self, fake_admin, fake_user, mock_user_repo):
        """Inviting existing email → ConflictError."""
        mock_user_repo.get_by_email = AsyncMock(return_value=fake_user)

        service = _make_user_service(mock_user_repo)

        with pytest.raises(ConflictError):
            await service.invite(
                admin=fake_admin,
                email="alice@example.com",
                role=UserRole.user,
            )

    async def test_non_admin_raises_forbidden(self, fake_user, mock_user_repo):
        """Non-admin caller → ForbiddenError."""
        service = _make_user_service(mock_user_repo)

        with pytest.raises(ForbiddenError):
            await service.invite(
                admin=fake_user,  # role=user, not admin
                email="someone@example.com",
                role=UserRole.user,
            )


# ---------------------------------------------------------------------------
# TestAcceptInvitation
# ---------------------------------------------------------------------------

class TestAcceptInvitation:
    async def test_valid_token_creates_user(self, mock_user_repo):
        """Valid invitation token → User created."""
        from datetime import datetime, timedelta, timezone
        invitation = MagicMock()
        invitation.accepted_at = None
        invitation.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        invitation.email = "invite@example.com"
        invitation.role = UserRole.user

        invitation_repo = AsyncMock()
        invitation_repo.get_by_token = AsyncMock(return_value=invitation)
        invitation_repo.mark_used = AsyncMock()
        mock_user_repo.create = AsyncMock(return_value=MagicMock())
        mock_user_repo.get_by_email = AsyncMock(return_value=None)

        service = _make_user_service(mock_user_repo, invitation_repo)

        result = await service.accept_invitation(
            token="valid_token",
            full_name="New User",
            password="SecurePass1!",
        )

        assert result is not None

    async def test_expired_token_raises_validation_error(self):
        """Expired invitation token → ValidationError."""
        from datetime import datetime, timedelta, timezone
        invitation = MagicMock()
        invitation.accepted_at = None
        invitation.expires_at = datetime.now(timezone.utc) - timedelta(days=1)

        user_repo = AsyncMock()
        invitation_repo = AsyncMock()
        invitation_repo.get_by_token = AsyncMock(return_value=invitation)

        service = _make_user_service(user_repo, invitation_repo)

        with pytest.raises(ValidationError):
            await service.accept_invitation(
                token="expired_token",
                full_name="Some User",
                password="SecurePass1!",
            )

    async def test_already_used_token_raises_conflict(self):
        """Already-used invitation token → ConflictError."""
        from datetime import datetime, timezone
        invitation = MagicMock()
        invitation.accepted_at = datetime.now(timezone.utc)

        user_repo = AsyncMock()
        invitation_repo = AsyncMock()
        invitation_repo.get_by_token = AsyncMock(return_value=invitation)

        service = _make_user_service(user_repo, invitation_repo)

        with pytest.raises(ConflictError):
            await service.accept_invitation(
                token="used_token",
                full_name="Some User",
                password="SecurePass1!",
            )


# ---------------------------------------------------------------------------
# TestDeactivateUser
# ---------------------------------------------------------------------------

class TestDeactivateUser:
    async def test_deactivate_sets_is_active_false(self, fake_admin, mock_user_repo):
        """Deactivating a user sets is_active=False."""
        import uuid as _uuid
        different_id = _uuid.uuid4()
        mock_user_repo.set_active = AsyncMock(return_value=MagicMock())

        service = _make_user_service(mock_user_repo)

        await service.deactivate_user(admin=fake_admin, target_id=different_id)

        mock_user_repo.set_active.assert_called_once_with(different_id, False)

    async def test_unknown_user_raises_not_found(self, fake_admin, mock_user_repo):
        """Deactivating unknown user id → NotFoundError."""
        import uuid
        mock_user_repo.set_active = AsyncMock(return_value=None)

        service = _make_user_service(mock_user_repo)

        with pytest.raises(NotFoundError):
            await service.deactivate_user(admin=fake_admin, target_id=uuid.uuid4())

    async def test_self_deactivation_raises_forbidden(self, fake_admin, mock_user_repo):
        """Admin cannot deactivate their own account → ForbiddenError."""
        mock_user_repo.get_by_id = AsyncMock(return_value=fake_admin)

        service = _make_user_service(mock_user_repo)

        with pytest.raises(ForbiddenError):
            await service.deactivate_user(admin=fake_admin, target_id=fake_admin.id)
