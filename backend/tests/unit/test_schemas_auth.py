"""Unit tests for Pydantic v2 auth & user schemas (T-024).

Covers:
  - Email normalisation (strip + lowercase)
  - Password-policy validators on RegisterRequest, AcceptInvitationRequest,
    ChangePasswordRequest
  - TokenResponse defaults
  - InviteRequest defaults
  - UserResponse.model_validate round-trip from ORM-like objects
  - UserResponse does NOT expose hashed_password
  - UserListResponse structure
  - UpdateUserRequest optional fields
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.schemas.auth import (
    AcceptInvitationRequest,
    ChangePasswordRequest,
    InviteRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)
from src.schemas.user import UpdateUserRequest, UserListResponse, UserResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

STRONG_PASSWORD = "Str0ng!Pass"
WEAK_PASSWORD = "short"


def _orm_user(**overrides):
    """Return an ORM-like namespace that mirrors the User model."""
    defaults = {
        "id": uuid.uuid4(),
        "email": "alice@example.com",
        "full_name": "Alice Smith",
        "role": "user",
        "is_active": True,
        "created_at": datetime.now(UTC),
        "hashed_password": "$2b$12$fakehash",
        "deleted_at": None,
        "updated_at": datetime.now(UTC),
        "must_change_password": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# LoginRequest
# ---------------------------------------------------------------------------

class TestLoginRequest:
    def test_valid(self):
        req = LoginRequest(email="User@EXAMPLE.com", password="whatever")
        assert req.email == "user@example.com"

    def test_email_stripped(self):
        req = LoginRequest(email="  bob@test.com  ", password="x")
        assert req.email == "bob@test.com"

    def test_missing_email(self):
        with pytest.raises(ValidationError):
            LoginRequest(password="x")

    def test_invalid_email(self):
        with pytest.raises(ValidationError):
            LoginRequest(email="not-an-email", password="x")


# ---------------------------------------------------------------------------
# TokenResponse
# ---------------------------------------------------------------------------

class TestTokenResponse:
    def test_defaults(self):
        tok = TokenResponse(access_token="abc", expires_in=3600)
        assert tok.token_type == "bearer"
        assert tok.expires_in == 3600

    def test_override_token_type(self):
        tok = TokenResponse(access_token="abc", token_type="mac", expires_in=60)
        assert tok.token_type == "mac"


# ---------------------------------------------------------------------------
# RegisterRequest
# ---------------------------------------------------------------------------

class TestRegisterRequest:
    def test_valid(self):
        req = RegisterRequest(
            email="NEW@Example.com",
            password=STRONG_PASSWORD,
            full_name="New User",
        )
        assert req.email == "new@example.com"

    def test_weak_password_rejected(self):
        with pytest.raises(ValidationError, match="[Pp]assword"):
            RegisterRequest(
                email="x@y.com",
                password=WEAK_PASSWORD,
                full_name="X",
            )

    def test_missing_full_name(self):
        with pytest.raises(ValidationError):
            RegisterRequest(email="x@y.com", password=STRONG_PASSWORD)


# ---------------------------------------------------------------------------
# InviteRequest
# ---------------------------------------------------------------------------

class TestInviteRequest:
    def test_defaults(self):
        req = InviteRequest(email="Invite@Test.COM")
        assert req.email == "invite@test.com"
        assert req.role == "user"

    def test_custom_role(self):
        req = InviteRequest(email="a@b.com", role="admin")
        assert req.role == "admin"


# ---------------------------------------------------------------------------
# AcceptInvitationRequest
# ---------------------------------------------------------------------------

class TestAcceptInvitationRequest:
    def test_valid(self):
        req = AcceptInvitationRequest(
            token="tok-abc",
            full_name="Bob",
            password=STRONG_PASSWORD,
        )
        assert req.token == "tok-abc"

    def test_weak_password_rejected(self):
        with pytest.raises(ValidationError, match="[Pp]assword"):
            AcceptInvitationRequest(
                token="tok",
                full_name="Bob",
                password=WEAK_PASSWORD,
            )


# ---------------------------------------------------------------------------
# ChangePasswordRequest
# ---------------------------------------------------------------------------

class TestChangePasswordRequest:
    def test_valid(self):
        req = ChangePasswordRequest(
            current_password="OldP@ss1",
            new_password=STRONG_PASSWORD,
        )
        assert req.new_password == STRONG_PASSWORD

    def test_weak_new_password_rejected(self):
        with pytest.raises(ValidationError, match="[Pp]assword"):
            ChangePasswordRequest(
                current_password="OldP@ss1",
                new_password=WEAK_PASSWORD,
            )


# ---------------------------------------------------------------------------
# UserResponse
# ---------------------------------------------------------------------------

class TestUserResponse:
    def test_from_orm(self):
        orm = _orm_user()
        resp = UserResponse.model_validate(orm)
        assert resp.id == orm.id
        assert resp.email == orm.email
        assert resp.full_name == orm.full_name
        assert resp.is_active is True

    def test_hashed_password_not_exposed(self):
        orm = _orm_user()
        resp = UserResponse.model_validate(orm)
        data = resp.model_dump()
        assert "hashed_password" not in data

    def test_deleted_at_not_exposed(self):
        orm = _orm_user()
        resp = UserResponse.model_validate(orm)
        data = resp.model_dump()
        assert "deleted_at" not in data

    def test_role_serialises_as_string(self):
        orm = _orm_user(role="admin")
        resp = UserResponse.model_validate(orm)
        assert resp.role.value == "admin"


# ---------------------------------------------------------------------------
# UserListResponse
# ---------------------------------------------------------------------------

class TestUserListResponse:
    def test_valid(self):
        orm_users = [_orm_user(), _orm_user(email="bob@x.com")]
        items = [UserResponse.model_validate(u) for u in orm_users]
        lst = UserListResponse(items=items, total=42, limit=10, offset=0)
        assert len(lst.items) == 2
        assert lst.total == 42

    def test_empty(self):
        lst = UserListResponse(items=[], total=0, limit=10, offset=0)
        assert lst.items == []


# ---------------------------------------------------------------------------
# UpdateUserRequest
# ---------------------------------------------------------------------------

class TestUpdateUserRequest:
    def test_all_none(self):
        req = UpdateUserRequest()
        assert req.full_name is None
        assert req.is_active is None

    def test_partial(self):
        req = UpdateUserRequest(full_name="Updated")
        assert req.full_name == "Updated"
        assert req.is_active is None
