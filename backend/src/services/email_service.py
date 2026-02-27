"""Email service – invitation and password-reset transactional emails.

Set ``EMAIL_LOG_ONLY=true`` in development to print email content to stdout
instead of connecting to an SMTP server.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Sends transactional emails.

    Set ``EMAIL_LOG_ONLY=true`` in development to print emails to stdout
    instead of connecting to an SMTP server.
    """

    # ── Public API ────────────────────────────────────────────────────

    async def send_invitation(self, to_email: str, raw_token: str) -> None:
        """Send account-setup invitation email."""
        setup_url = f"{settings.FRONTEND_URL}/auth/setup?token={raw_token}"
        subject = "You've been invited to Internal Knowledge AI Agent"
        body_text = (
            "You have been invited to join Internal Knowledge AI Agent.\n\n"
            "Click the link below to set your password and activate your account:\n\n"
            f"{setup_url}\n\n"
            "This link expires in 7 days. Do not share it with anyone.\n"
        )
        body_html = (
            "<p>You have been invited to join "
            "<strong>Internal Knowledge AI Agent</strong>.</p>"
            f'<p><a href="{setup_url}">Set your password →</a></p>'
            "<p>This link expires in 7 days. Do not share it with anyone.</p>"
        )
        await self._send(to_email, subject, body_text, body_html)

    async def send_password_reset(self, to_email: str, raw_token: str) -> None:
        """Send password reset email."""
        reset_url = (
            f"{settings.FRONTEND_URL}/auth/password-reset/confirm?token={raw_token}"
        )
        subject = "Password Reset — Internal Knowledge AI Agent"
        body_text = (
            "A password reset was requested for your account.\n\n"
            "Click the link below to set a new password:\n\n"
            f"{reset_url}\n\n"
            "This link expires in 1 hour. "
            "If you did not request this, ignore this email.\n"
        )
        body_html = (
            "<p>A password reset was requested for your account.</p>"
            f'<p><a href="{reset_url}">Reset your password →</a></p>'
            "<p>This link expires in 1 hour. "
            "If you did not request this, you can safely ignore this email.</p>"
        )
        await self._send(to_email, subject, body_text, body_html)

    # ── Internal ──────────────────────────────────────────────────────

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
