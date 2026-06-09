"""Unit tests for User, Invitation, and UserRole models.

All tests are sync and require NO database connection — they exercise
pure-Python behaviour: column metadata, defaults, properties, enums,
and relationship declarations.

Follows the same pattern as ``test_base_models.py``.
"""
from __future__ import annotations

import uuid

from src.models.user import Invitation, User, UserRole

# ===================================================================
# UserRole enum
# ===================================================================

class TestUserRole:
    """Validate the UserRole enum members and behaviour."""

    def test_enum_has_admin_value(self):
        assert UserRole.admin.value == "admin"

    def test_enum_has_user_value(self):
        assert UserRole.user.value == "user"

    def test_enum_members_count(self):
        """UserRole should have exactly two members."""
        assert len(UserRole) == 2

    def test_enum_is_str_subclass(self):
        """UserRole inherits str so its value is directly usable as text."""
        assert isinstance(UserRole.admin, str)
        assert isinstance(UserRole.user, str)


# ===================================================================
# User model — column metadata
# ===================================================================

class TestUserColumns:
    """Verify every required column is declared with correct metadata."""

    cols = User.__table__.columns

    def test_id_column_exists(self):
        assert "id" in self.cols

    def test_email_column_exists(self):
        assert "email" in self.cols

    def test_email_max_length(self):
        assert self.cols["email"].type.length == 254

    def test_email_not_nullable(self):
        assert self.cols["email"].nullable is False

    def test_email_is_unique(self):
        assert self.cols["email"].unique is True

    def test_email_is_indexed(self):
        assert self.cols["email"].index is True

    def test_hashed_password_column_exists(self):
        assert "hashed_password" in self.cols

    def test_hashed_password_max_length(self):
        assert self.cols["hashed_password"].type.length == 60

    def test_hashed_password_not_nullable(self):
        assert self.cols["hashed_password"].nullable is False

    def test_full_name_column_exists(self):
        assert "full_name" in self.cols

    def test_full_name_max_length(self):
        assert self.cols["full_name"].type.length == 200

    def test_full_name_not_nullable(self):
        assert self.cols["full_name"].nullable is False

    def test_role_column_exists(self):
        assert "role" in self.cols

    def test_role_not_nullable(self):
        assert self.cols["role"].nullable is False

    def test_is_active_column_exists(self):
        assert "is_active" in self.cols

    def test_is_active_not_nullable(self):
        assert self.cols["is_active"].nullable is False

    def test_must_change_password_column_exists(self):
        assert "must_change_password" in self.cols

    def test_must_change_password_not_nullable(self):
        assert self.cols["must_change_password"].nullable is False

    # Inherited from mixins
    def test_created_at_column_exists(self):
        assert "created_at" in self.cols

    def test_updated_at_column_exists(self):
        assert "updated_at" in self.cols

    def test_deleted_at_column_exists(self):
        assert "deleted_at" in self.cols

    def test_deleted_at_is_nullable(self):
        assert self.cols["deleted_at"].nullable is True

    def test_timestamp_columns_timezone_aware(self):
        for name in ("created_at", "updated_at"):
            assert self.cols[name].type.timezone is True, f"{name} must be tz-aware"


# ===================================================================
# User model — defaults and behaviour
# ===================================================================

class TestUserDefaults:
    """Verify column-level defaults (applied at INSERT time by SQLAlchemy)."""

    def test_default_role_is_user(self):
        col = User.__table__.columns["role"]
        assert col.default.arg == UserRole.user

    def test_default_is_active_true(self):
        col = User.__table__.columns["is_active"]
        assert col.default.arg is True

    def test_default_must_change_password_false(self):
        col = User.__table__.columns["must_change_password"]
        assert col.default.arg is False

    def test_explicit_id_is_respected(self):
        explicit = uuid.uuid4()
        u = User(
            id=explicit,
            email="a@b.com",
            hashed_password="x" * 60,
            full_name="Test",
        )
        assert u.id == explicit

    def test_tablename_is_users(self):
        assert User.__tablename__ == "users"


# ===================================================================
# User — soft-delete (inherits SoftDeleteMixin)
# ===================================================================

class TestUserSoftDelete:
    """User has SoftDeleteMixin so soft_delete/is_deleted must work."""

    def _make(self) -> User:
        return User(
            email="a@b.com",
            hashed_password="x" * 60,
            full_name="Test",
        )

    def test_new_user_is_not_deleted(self):
        assert self._make().is_deleted is False

    def test_soft_delete_sets_deleted_at(self):
        u = self._make()
        u.soft_delete()
        assert u.deleted_at is not None

    def test_is_deleted_true_after_soft_delete(self):
        u = self._make()
        u.soft_delete()
        assert u.is_deleted is True

    def test_soft_delete_timestamp_is_tz_aware(self):
        u = self._make()
        u.soft_delete()
        assert u.deleted_at.tzinfo is not None


# ===================================================================
# User — to_dict
# ===================================================================

class TestUserToDict:
    """User inherits Base.to_dict — ensure it surfaces all columns."""

    def test_returns_dict(self):
        u = User(
            email="a@b.com",
            hashed_password="x" * 60,
            full_name="Test",
        )
        assert isinstance(u.to_dict(), dict)

    def test_contains_all_user_columns(self):
        u = User(
            email="a@b.com",
            hashed_password="x" * 60,
            full_name="Test",
        )
        d = u.to_dict()
        for col in (
            "id", "email", "hashed_password", "full_name", "role",
            "is_active", "must_change_password",
            "created_at", "updated_at", "deleted_at",
        ):
            assert col in d, f"to_dict() missing '{col}'"


# ===================================================================
# User — relationships declared
# ===================================================================

class TestUserRelationships:
    """Verify that relationship properties are declared (no DB required)."""

    def test_refresh_tokens_relationship_exists(self):
        assert hasattr(User, "refresh_tokens")

    def test_invitations_sent_relationship_exists(self):
        assert hasattr(User, "invitations_sent")


# ===================================================================
# Invitation model — column metadata
# ===================================================================

class TestInvitationColumns:
    """Verify every required column on the Invitation table."""

    cols = Invitation.__table__.columns

    def test_id_column_exists(self):
        assert "id" in self.cols

    def test_email_column_exists(self):
        assert "email" in self.cols

    def test_email_max_length(self):
        assert self.cols["email"].type.length == 254

    def test_email_not_nullable(self):
        assert self.cols["email"].nullable is False

    def test_email_is_indexed(self):
        assert self.cols["email"].index is True

    def test_token_column_exists(self):
        assert "token" in self.cols

    def test_token_max_length(self):
        # Stored token is the SHA-256 hex digest of secrets.token_urlsafe()
        # → always 64 chars (see migration 0005_expand_invitation_token).
        assert self.cols["token"].type.length == 64

    def test_token_not_nullable(self):
        assert self.cols["token"].nullable is False

    def test_token_is_unique(self):
        assert self.cols["token"].unique is True

    def test_token_is_indexed(self):
        assert self.cols["token"].index is True

    def test_invited_by_column_exists(self):
        assert "invited_by" in self.cols

    def test_invited_by_is_nullable(self):
        assert self.cols["invited_by"].nullable is True

    def test_invited_by_has_fk_to_users_id(self):
        fks = self.cols["invited_by"].foreign_keys
        assert len(fks) == 1
        fk = next(iter(fks))
        assert fk.target_fullname == "users.id"

    def test_role_column_exists(self):
        assert "role" in self.cols

    def test_role_not_nullable(self):
        assert self.cols["role"].nullable is False

    def test_expires_at_column_exists(self):
        assert "expires_at" in self.cols

    def test_expires_at_not_nullable(self):
        assert self.cols["expires_at"].nullable is False

    def test_expires_at_is_tz_aware(self):
        assert self.cols["expires_at"].type.timezone is True

    def test_accepted_at_column_exists(self):
        assert "accepted_at" in self.cols

    def test_accepted_at_is_nullable(self):
        assert self.cols["accepted_at"].nullable is True

    # Inherited from TimestampMixin
    def test_created_at_exists(self):
        assert "created_at" in self.cols

    def test_updated_at_exists(self):
        assert "updated_at" in self.cols


# ===================================================================
# Invitation — NO soft-delete
# ===================================================================

class TestInvitationNoSoftDelete:
    """Invitation should NOT have soft-delete columns or methods."""

    def test_no_deleted_at_column(self):
        assert "deleted_at" not in Invitation.__table__.columns

    def test_no_is_deleted_property(self):
        """is_deleted comes from SoftDeleteMixin — should be absent."""
        inv = Invitation(
            email="a@b.com",
            token="t" * 36,
        )
        assert not hasattr(inv, "is_deleted")

    def test_no_soft_delete_method(self):
        inv = Invitation(
            email="a@b.com",
            token="t" * 36,
        )
        assert not hasattr(inv, "soft_delete")


# ===================================================================
# Invitation — defaults and behaviour
# ===================================================================

class TestInvitationDefaults:

    def test_tablename_is_invitations(self):
        assert Invitation.__tablename__ == "invitations"

    def test_default_role_is_user(self):
        col = Invitation.__table__.columns["role"]
        assert col.default.arg == UserRole.user

    def test_accepted_at_default_none(self):
        inv = Invitation(
            email="a@b.com",
            token="t" * 36,
        )
        assert inv.accepted_at is None


# ===================================================================
# Invitation — to_dict
# ===================================================================

class TestInvitationToDict:

    def test_returns_dict(self):
        inv = Invitation(email="a@b.com", token="t" * 36)
        assert isinstance(inv.to_dict(), dict)

    def test_contains_all_columns(self):
        inv = Invitation(email="a@b.com", token="t" * 36)
        d = inv.to_dict()
        for col in (
            "id", "email", "token", "invited_by", "role",
            "expires_at", "accepted_at", "created_at", "updated_at",
        ):
            assert col in d, f"to_dict() missing '{col}'"


# ===================================================================
# Invitation — relationship declared
# ===================================================================

class TestInvitationRelationships:

    def test_invited_by_user_relationship_exists(self):
        assert hasattr(Invitation, "invited_by_user")
