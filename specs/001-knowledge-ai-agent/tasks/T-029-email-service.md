# T-029 — Email Service (Invitation + Password Reset)

## Metadata
| Field | Value |
|---|---|
| **ID** | T-029 |
| **Title** | Email Service — invitation link + password reset emails |
| **Phase** | 1 — Authentication & User Management |
| **Domain** | Backend / Infrastructure |
| **Depends on** | T-004 |
| **Blocks** | T-026, T-028, T-030 |
| **Est. complexity** | S |

---

## Goal
Implement `EmailService` — a simple abstraction over SMTP (or a dev console logger). In development it logs the email content to stdout (`LOG_EMAILS=true`). In production it sends via SMTP. The service is injected via the dependency-injector container, so switching providers requires only a config change.

---

## Deliverables

### 1. `app/core/config.py` additions
```python
class Settings(BaseSettings):
    # ── Email ──────────────────────────────────────────────────────────
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "noreply@knowledge-agent.internal"
    SMTP_USE_TLS: bool = True

    # Dev shortcut: log emails to stdout instead of sending
    EMAIL_LOG_ONLY: bool = False

    # Frontend URL — needed to build links in emails
    FRONTEND_URL: str = "http://localhost:3000"
```

---

### 2. `app/services/email_service.py`
```python
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """
    Sends transactional emails.

    Set `EMAIL_LOG_ONLY=true` in development to print emails to stdout
    instead of connecting to an SMTP server.
    """

    async def send_invitation(self, to_email: str, raw_token: str) -> None:
        """Send account-setup invitation email."""
        setup_url = (
            f"{settings.FRONTEND_URL}/auth/setup?token={raw_token}"
        )
        subject = "You've been invited to Internal Knowledge AI Agent"
        body_text = (
            f"You have been invited to join Internal Knowledge AI Agent.\n\n"
            f"Click the link below to set your password and activate your account:\n\n"
            f"{setup_url}\n\n"
            f"This link expires in 7 days. Do not share it with anyone.\n"
        )
        body_html = f"""
        <p>You have been invited to join <strong>Internal Knowledge AI Agent</strong>.</p>
        <p><a href="{setup_url}">Set your password →</a></p>
        <p>This link expires in 7 days. Do not share it with anyone.</p>
        """
        await self._send(to_email, subject, body_text, body_html)

    async def send_password_reset(self, to_email: str, raw_token: str) -> None:
        """Send password reset email."""
        reset_url = (
            f"{settings.FRONTEND_URL}/auth/password-reset/confirm?token={raw_token}"
        )
        subject = "Password Reset — Internal Knowledge AI Agent"
        body_text = (
            f"A password reset was requested for your account.\n\n"
            f"Click the link below to set a new password:\n\n"
            f"{reset_url}\n\n"
            f"This link expires in 1 hour. If you did not request this, ignore this email.\n"
        )
        body_html = f"""
        <p>A password reset was requested for your account.</p>
        <p><a href="{reset_url}">Reset your password →</a></p>
        <p>This link expires in 1 hour. If you did not request this, you can safely ignore this email.</p>
        """
        await self._send(to_email, subject, body_text, body_html)

    # ─── Internal ─────────────────────────────────────────────────────────

    async def _send(
        self, to: str, subject: str, body_text: str, body_html: str
    ) -> None:
        if settings.EMAIL_LOG_ONLY:
            logger.info(
                "EMAIL (log-only) to=%s subject=%r\n%s",
                to,
                subject,
                body_text,
            )
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to
        msg.attach(MIMEText(body_text, "plain"))
        msg.attach(MIMEText(body_html, "html"))

        try:
            import asyncio
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._send_sync, to, msg)
        except Exception as exc:
            logger.error(
                "Failed to send email to %s: %s", to, exc, exc_info=True
            )
            # Do NOT re-raise — email failure must not 500 the API response

    def _send_sync(self, to: str, msg: MIMEMultipart) -> None:
        """Blocking SMTP call run in a thread-pool executor."""
        if settings.SMTP_USE_TLS:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)

        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)

        server.sendmail(settings.SMTP_FROM, to, msg.as_string())
        server.quit()
```

### 3. Register in DI container (`app/containers.py`)
```python
from app.services.email_service import EmailService

class Container(containers.DeclarativeContainer):
    ...
    email_service = providers.Singleton(EmailService)
```

---

## Dev Setup: Mailpit (already in Docker Compose from T-002 as optional)
In development, set:
```env
SMTP_HOST=mailpit
SMTP_PORT=1025
EMAIL_LOG_ONLY=false
```
Mailpit exposes a web UI on port 8025 where sent emails appear. For CI and unit tests, use `EMAIL_LOG_ONLY=true`.

---

## Acceptance Criteria
- [ ] `EmailService.send_invitation()` builds correct URL: `{FRONTEND_URL}/auth/setup?token={token}`
- [ ] `EmailService.send_password_reset()` builds correct URL: `{FRONTEND_URL}/auth/password-reset/confirm?token={token}`
- [ ] When `EMAIL_LOG_ONLY=true`, logs email content and returns without SMTP connection attempt
- [ ] SMTP failures are caught and logged — they do NOT re-raise (API response is not affected)
- [ ] All SMTP calls run in a thread-pool executor (non-blocking async)
- [ ] Unit tests: invitation URL assembled correctly, reset URL assembled correctly, log-only mode does not call SMTP
- [ ] `EmailService` registered as `Singleton` in DI container

---

## Notes
- Token is passed RAW to the email service; the service does no hashing (T-025 already stored the hash)
- `send_invitation` and `send_password_reset` are the only two email templates needed for Phase 1
- Both methods return `None` — callers must not depend on a return value
