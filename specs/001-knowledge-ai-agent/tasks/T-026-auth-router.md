# T-026 â€” Auth FastAPI Router (7 endpoints)

## Metadata
| Field | Value |
|---|---|
| **Status** | Done |
| **ID** | T-026 |
| **Title** | Auth FastAPI Router â€” login, refresh, logout, setup, password-reset, change-password |
| **Phase** | 1 â€” Authentication & User Management |
| **Domain** | Backend / API |
| **Depends on** | T-015, T-016, T-017, T-024, T-025, T-027 |
| **Blocks** | T-030, T-036, T-037 |
| **Est. complexity** | M |

### Project Standards
_(see T-025 header â€” same project standards apply to all tasks)_

---

## Goal
Build the 7-endpoint auth router at `POST /api/v1/auth/*`. Every response is RFC 7807-compliant for errors, JSON for success. Refresh cookie management, CSRF token issuance, and the `must_change_password` flag in the response all handled here.

---

## API Contract (from `contracts/auth.yaml`)

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/login` | Public | Credentials â†’ access token + refresh cookie |
| `POST` | `/auth/refresh` | httpOnly cookie | Rotate tokens |
| `POST` | `/auth/logout` | Bearer | Revoke refresh token + clear cookie |
| `POST` | `/auth/setup` | Public (invite token) | Accept invitation, set password |
| `POST` | `/auth/password-reset` | Public | Request reset link (always 202) |
| `POST` | `/auth/password-reset/confirm` | Public | Confirm reset with token + new password |
| `POST` | `/auth/change-password` | Bearer | Voluntary or forced change |

---

## Deliverables

### 1. `app/api/v1/auth.py`
```python
from fastapi import APIRouter, Response, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.containers import get_auth_service, get_email_service
from app.core.security import set_refresh_cookie, clear_refresh_cookie, set_csrf_cookie
from app.core.deps import require_authenticated
from app.schemas.auth import (
    LoginRequest, TokenResponse,
    InvitationSetupRequest,
    PasswordResetRequest, PasswordResetConfirmRequest,
    ChangePasswordRequest,
)
from app.services.auth_service import AuthService
from app.services.email_service import EmailService

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# POST /auth/login
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service),
):
    access, refresh_raw, must_change = await auth_svc.login(body.email, body.password)
    set_refresh_cookie(response, refresh_raw)
    set_csrf_cookie(response)
    return TokenResponse(
        access_token=access,
        token_type="Bearer",
        expires_in=900,
        must_change_password=must_change,
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# POST /auth/refresh
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: str = Depends(_cookie_token),   # see helper below
    auth_svc: AuthService = Depends(get_auth_service),
):
    access, refresh_raw, must_change = await auth_svc.refresh(refresh_token)
    set_refresh_cookie(response, refresh_raw)
    set_csrf_cookie(response)
    return TokenResponse(
        access_token=access,
        token_type="Bearer",
        expires_in=900,
        must_change_password=must_change,
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# POST /auth/logout
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    refresh_token: str = Depends(_cookie_token),
    auth_svc: AuthService = Depends(get_auth_service),
    _current: dict = Depends(require_authenticated),
):
    await auth_svc.logout(refresh_token)
    clear_refresh_cookie(response)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# POST /auth/setup  (accept invitation)
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.post("/setup", response_model=TokenResponse, status_code=status.HTTP_200_OK)
async def setup_account(
    body: InvitationSetupRequest,
    response: Response,
    auth_svc: AuthService = Depends(get_auth_service),
):
    access, refresh_raw, must_change = await auth_svc.accept_invitation(
        body.token, body.password
    )
    set_refresh_cookie(response, refresh_raw)
    set_csrf_cookie(response)
    return TokenResponse(
        access_token=access,
        token_type="Bearer",
        expires_in=900,
        must_change_password=must_change,
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# POST /auth/password-reset
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.post(
    "/password-reset",
    status_code=status.HTTP_202_ACCEPTED,
    # Always returns 202 â€” never reveals whether email exists
)
async def request_password_reset(
    body: PasswordResetRequest,
    auth_svc: AuthService = Depends(get_auth_service),
    email_svc: EmailService = Depends(get_email_service),
):
    raw_token = await auth_svc.request_password_reset(body.email)
    # Fire-and-forget: send email only when token was generated
    if raw_token:
        await email_svc.send_password_reset(body.email, raw_token)
    return {"detail": "If your email is registered, you will receive a reset link."}


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# POST /auth/password-reset/confirm
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    body: PasswordResetConfirmRequest,
    auth_svc: AuthService = Depends(get_auth_service),
):
    await auth_svc.confirm_password_reset(body.token, body.new_password)


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# POST /auth/change-password
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    auth_svc: AuthService = Depends(get_auth_service),
    current: dict = Depends(require_authenticated),
):
    await auth_svc.change_password(
        current["user_id"],
        body.current_password,
        body.new_password,
    )


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Internal dependency helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
from fastapi import Cookie, HTTPException

async def _cookie_token(refresh_token: str | None = Cookie(default=None)) -> str:
    if not refresh_token:
        from app.core.errors import UnauthorizedError
        raise UnauthorizedError("Refresh token cookie missing")
    return refresh_token
```

### 2. Register in `app/api/v1/router.py`
```python
from app.api.v1.auth import router as auth_router

api_v1_router.include_router(auth_router)   # prefix="/auth" is set on the router itself
```

---

## Acceptance Criteria
- [ ] `POST /auth/login` with valid creds â†’ `200 TokenResponse` + `Set-Cookie: refresh_token` + CSRF cookie
- [ ] `POST /auth/login` with invalid creds â†’ `401 application/problem+json`
- [ ] `POST /auth/login` for inactive user â†’ `403 application/problem+json`
- [ ] `POST /auth/refresh` with valid cookie â†’ `200 TokenResponse` + rotated cookie
- [ ] `POST /auth/refresh` without cookie â†’ `401`
- [ ] `POST /auth/logout` with valid token â†’ `204` + cleared cookie
- [ ] `POST /auth/setup` with valid invite token + compliant password â†’ `200 TokenResponse`
- [ ] `POST /auth/setup` with expired token â†’ `410` (handled by `AuthService.accept_invitation`)
- [ ] `POST /auth/password-reset` always returns `202` regardless of whether email exists
- [ ] `POST /auth/password-reset/confirm` with valid token â†’ `204`
- [ ] `POST /auth/password-reset/confirm` with expired token â†’ `401`
- [ ] `POST /auth/change-password` with correct current password â†’ `204`
- [ ] `POST /auth/change-password` with wrong current password â†’ `401`
- [ ] All error responses use `application/problem+json` content-type
- [ ] Router registered in `api_v1_router`; accessible at `/api/v1/auth/*`

---

## FR References
| FR | Requirement |
|---|---|
| FR-021 | Invitation-only account creation path (`/setup`) |
| FR-023 | Password reset via time-limited email link |
| FR-024 | `must_change_password` returned in `TokenResponse` |
| FR-034 | Password policy enforced on setup, reset, and change operations |
