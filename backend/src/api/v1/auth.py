"""Auth router – login, token refresh, logout, invitation setup, password flows.

All endpoints live under ``/api/v1/auth`` (prefix set via
:func:`include_router` in :mod:`src.api.v1.router`).
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.database import get_db
from src.core.deps import require_authenticated
from src.core.exceptions import UnauthorizedError
from src.core.security import (
    clear_refresh_cookie,
    set_csrf_cookie,
    set_refresh_cookie,
)
from src.models.user import User
from src.repositories.admin_audit_log_repository import AdminAuditLogRepository
from src.repositories.invitation_repository import InvitationRepository
from src.repositories.refresh_token_repository import RefreshTokenRepository
from src.repositories.user_repository import UserRepository
from src.schemas.auth import (
    AcceptInvitationRequest,
    ChangePasswordRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    TokenResponse,
)
from src.services.audit_service import emit_audit
from src.services.auth_service import AuthService
from src.services.password_service import PasswordService
from src.services.user_service import UserService

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def _get_auth_service(
    db: AsyncSession = Depends(get_db),
) -> AuthService:
    """Construct :class:`AuthService` bound to the request-scoped DB session.

    Replaces the legacy ``Container.auth_service()`` resolver, which built
    every repository against a *separate* :class:`AsyncSession` — leaving the
    refresh-token row in an uncommitted, GC-rollback'd session while the
    route handler committed only its audit-log session. The result was a
    refresh-token cookie pointing at a row that never landed in the DB and
    a 401 on the very next ``/auth/refresh``.

    All repositories AND the inner :class:`UserService` now share the same
    :class:`AsyncSession` so the refresh-token row written by
    ``_issue_tokens`` lives in the same transaction as the audit-log row
    written by the route handler. :class:`AuthService` commits the session
    itself at the end of every mutating method.

    Tests continue to override this symbol via
    ``app.dependency_overrides[_get_auth_service] = ...`` to inject mocks —
    FastAPI ignores the dependency parameters when an override is active.
    """
    from src.core.container import Container  # noqa: PLC0415

    user_repo = UserRepository(session=db)
    refresh_repo = RefreshTokenRepository(session=db)
    user_service = UserService(
        user_repo=user_repo,
        invitation_repo=InvitationRepository(session=db),
        password_service=PasswordService(),
        refresh_token_repo=refresh_repo,
        email_service=Container.email_service(),
    )
    return AuthService(
        user_repo=user_repo,
        refresh_repo=refresh_repo,
        user_service=user_service,
        password_service=PasswordService(),
        session=db,
        lockout=Container.account_lockout(),
    )


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
    *,
    remember_me: bool = False,
) -> TokenResponse:
    """Build a :class:`TokenResponse` and attach refresh / CSRF cookies."""
    set_refresh_cookie(response, refresh_token, remember_me=remember_me)
    set_csrf_cookie(response, secrets.token_urlsafe(32), remember_me=remember_me)
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
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(_get_auth_service),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate with email / password and receive tokens."""
    audit_repo = AdminAuditLogRepository(db)
    try:
        access, refresh, mcp = await auth_service.login(body.email, body.password)
    except UnauthorizedError:
        await emit_audit(
            audit_repo,
            admin_user_id=None,
            action="login_failure",
            resource_type="user",
            resource_id=None,
            request=request,
            metadata={"email": body.email, "reason": "invalid_credentials"},
        )
        await db.commit()
        raise

    # Resolve user id for the audit row (login succeeded so the user exists).
    from src.repositories.user_repository import UserRepository  # noqa: PLC0415

    authenticated_user = await UserRepository(db).get_by_email(body.email)
    user_id = authenticated_user.id if authenticated_user is not None else None
    await emit_audit(
        audit_repo,
        admin_user_id=user_id,
        action="login_success",
        resource_type="user",
        resource_id=user_id,
        request=request,
        metadata={},
    )
    await db.commit()
    return _token_response(response, access, refresh, mcp, remember_me=body.remember_me)


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
