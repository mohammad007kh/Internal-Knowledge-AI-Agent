"""Pydantic v2 schemas for auth endpoints (T-024).

Covers login, token response, registration, invitation, and
password-change request/response contracts.
"""

from pydantic import BaseModel, EmailStr, field_validator

from src.services.password_service import PasswordService


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    """POST /auth/login body."""

    email: EmailStr
    password: str

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

class TokenResponse(BaseModel):
    """Returned after successful authentication."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds
    must_change_password: bool = False


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    """POST /auth/register body."""

    email: EmailStr
    password: str
    full_name: str

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_pw(cls, v: str) -> str:
        PasswordService.validate_password_policy(v)
        return v


# ---------------------------------------------------------------------------
# Invitation
# ---------------------------------------------------------------------------

class InviteRequest(BaseModel):
    """POST /admin/invitations body."""

    email: EmailStr
    role: str = "user"

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class AcceptInvitationRequest(BaseModel):
    """POST /auth/accept-invitation body."""

    token: str
    full_name: str
    password: str

    @field_validator("password")
    @classmethod
    def validate_pw(cls, v: str) -> str:
        PasswordService.validate_password_policy(v)
        return v


# ---------------------------------------------------------------------------
# Change password
# ---------------------------------------------------------------------------

class ChangePasswordRequest(BaseModel):
    """POST /auth/change-password body."""

    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_pw(cls, v: str) -> str:
        PasswordService.validate_password_policy(v)
        return v


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


class PasswordResetRequest(BaseModel):
    """POST /auth/password-reset body."""

    email: EmailStr

    @field_validator("email", mode="before")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return v.strip().lower()


class PasswordResetConfirmRequest(BaseModel):
    """POST /auth/password-reset/confirm body."""

    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_pw(cls, v: str) -> str:
        PasswordService.validate_password_policy(v)
        return v
