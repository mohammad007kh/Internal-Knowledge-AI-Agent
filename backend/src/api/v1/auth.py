"""Auth router – login, token refresh, logout, invitation setup, password flows.

All endpoints live under ``/api/v1/auth`` (prefix set via
:func:`include_router` in :mod:`src.api.v1.router`).
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request, Response, status

from src.core.config import settings
from src.core.deps import require_authenticated
from src.core.exceptions import UnauthorizedError
from src.core.security import (
    clear_refresh_cookie,
    set_csrf_cookie,
    set_refresh_cookie,
)
from src.models.user import User
from src.schemas.auth import (
    AcceptInvitationRequest,
    ChangePasswordRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    TokenResponse,
)
from src.services.auth_service import AuthService

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def _get_auth_service() -> AuthService:
    """Resolve :class:`AuthService` from the DI container.

    Uses a lazy import so that the module can be loaded without triggering
    the full container wiring (helpful for unit tests).
    """
    from src.core.container import Container  # noqa: PLC0415

    return Container.auth_service()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cookie_token(request: Request) -> str:
    """Extract the refresh-token value from the httpOnly cookie.

    Raises :class:`UnauthorizedError` when the cookie is absent.
    """
    token = request.cookies.get("refresh_token")
    if not token:
        raise UnauthorizedError("Missing refresh token cookie")
    return token


def _token_response(
    response: Response,
    access_token: str,
    refresh_token: str,
    must_change_password: bool,
) -> TokenResponse:
    """Build a :class:`TokenResponse` and attach refresh / CSRF cookies."""
    set_refresh_cookie(response, refresh_token)
    set_csrf_cookie(response, secrets.token_urlsafe(32))
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        must_change_password=must_change_password,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def login(
    body: LoginRequest,
    response: Response,
    auth_service: AuthService = Depends(_get_auth_service),
) -> TokenResponse:
    """Authenticate with email / password and receive tokens."""
    access, refresh, mcp = await auth_service.login(body.email, body.password)
    return _token_response(response, access, refresh, mcp)


@router.post("/refresh", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def refresh(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(_get_auth_service),
) -> TokenResponse:
    """Rotate the refresh token and issue a new access token."""
    raw = _cookie_token(request)
    access, new_refresh, mcp = await auth_service.refresh(raw)
    return _token_response(response, access, new_refresh, mcp)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(require_authenticated),  # noqa: ARG001
    auth_service: AuthService = Depends(_get_auth_service),
) -> None:
    """Revoke the refresh token and clear the cookie."""
    token = request.cookies.get("refresh_token")
    if token:
        await auth_service.logout(token)
    clear_refresh_cookie(response)


@router.post("/setup", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def setup(
    body: AcceptInvitationRequest,
    response: Response,
    auth_service: AuthService = Depends(_get_auth_service),
) -> TokenResponse:
    """Accept an invitation and create a new user account."""
    access, refresh_tok, mcp = await auth_service.accept_invitation(
        body.token,
        body.full_name,
        body.password,
    )
    return _token_response(response, access, refresh_tok, mcp)


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def password_reset(
    body: PasswordResetRequest,
    auth_service: AuthService = Depends(_get_auth_service),
) -> dict[str, str]:
    """Request a password-reset email.

    Always returns 202 to prevent user enumeration.
    """
    await auth_service.request_password_reset(body.email)
    return {"message": "If the email exists, a reset link has been sent."}


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def password_reset_confirm(
    body: PasswordResetConfirmRequest,
    auth_service: AuthService = Depends(_get_auth_service),
) -> None:
    """Set a new password using a valid reset token."""
    await auth_service.confirm_password_reset(body.token, body.new_password)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_user: User = Depends(require_authenticated),
    auth_service: AuthService = Depends(_get_auth_service),
) -> None:
    """Change password for the authenticated user."""
    await auth_service.change_password(
        current_user.id,
        body.current_password,
        body.new_password,
    )
