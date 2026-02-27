"""Unit tests for EmailService (T-029)."""

from __future__ import annotations

import os

# Required env vars — must be set BEFORE any src.* imports
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-refresh-secret")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "minioadmin")
os.environ.setdefault("MINIO_SECRET_KEY", "minioadmin")
os.environ.setdefault("ENCRYPTION_KEY", "a" * 64)

import asyncio
from email.mime.multipart import MIMEMultipart
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.email_service import EmailService


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture()
def email_service() -> EmailService:
    return EmailService()


# ── Invitation URL tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_invitation_builds_correct_url_log_only(
    email_service: EmailService,
) -> None:
    """Invitation email must contain {FRONTEND_URL}/auth/setup?token={token}."""
    with patch.object(
        type(email_service)._send.__func__.__class__,
        "__call__",
        new_callable=AsyncMock,
    ) if False else patch.object(
        email_service, "_send", new_callable=AsyncMock
    ) as mock_send:
        await email_service.send_invitation("user@example.com", "tok-abc")

    mock_send.assert_awaited_once()
    args = mock_send.call_args
    to = args[0][0]
    subject = args[0][1]
    body_text = args[0][2]
    body_html = args[0][3]

    assert to == "user@example.com"
    assert "invited" in subject.lower() or "invitation" in subject.lower()
    assert "http://localhost:3000/auth/setup?token=tok-abc" in body_text
    assert "http://localhost:3000/auth/setup?token=tok-abc" in body_html


@pytest.mark.asyncio
async def test_send_invitation_url_with_custom_frontend(
    email_service: EmailService,
) -> None:
    """If FRONTEND_URL changes, the invitation URL must follow."""
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch.object(email_service, "_send", new_callable=AsyncMock) as mock_send,
    ):
        mock_settings.FRONTEND_URL = "https://app.example.com"
        await email_service.send_invitation("u@e.com", "t1")

    body_text = mock_send.call_args[0][2]
    assert "https://app.example.com/auth/setup?token=t1" in body_text


# ── Password-reset URL tests ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_password_reset_builds_correct_url(
    email_service: EmailService,
) -> None:
    """Reset email must contain {FRONTEND_URL}/auth/password-reset/confirm?token={token}."""
    with patch.object(
        email_service, "_send", new_callable=AsyncMock
    ) as mock_send:
        await email_service.send_password_reset("user@example.com", "rst-xyz")

    mock_send.assert_awaited_once()
    body_text = mock_send.call_args[0][2]
    body_html = mock_send.call_args[0][3]

    expected_url = "http://localhost:3000/auth/password-reset/confirm?token=rst-xyz"
    assert expected_url in body_text
    assert expected_url in body_html


@pytest.mark.asyncio
async def test_send_password_reset_url_with_custom_frontend(
    email_service: EmailService,
) -> None:
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch.object(email_service, "_send", new_callable=AsyncMock) as mock_send,
    ):
        mock_settings.FRONTEND_URL = "https://custom.host"
        await email_service.send_password_reset("u@e.com", "tok-1")

    body_text = mock_send.call_args[0][2]
    assert "https://custom.host/auth/password-reset/confirm?token=tok-1" in body_text


# ── Log-only mode tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_log_only_mode_does_not_call_smtp(
    email_service: EmailService,
) -> None:
    """When EMAIL_LOG_ONLY=true, no SMTP connection must occur."""
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch("src.services.email_service.logger") as mock_logger,
        patch.object(email_service, "_send_sync") as mock_smtp_sync,
    ):
        mock_settings.EMAIL_LOG_ONLY = True
        await email_service._send("a@b.com", "subj", "text", "<p>html</p>")

    mock_smtp_sync.assert_not_called()
    mock_logger.info.assert_called_once()
    log_msg = mock_logger.info.call_args[0][0]
    assert "log-only" in log_msg.lower()


@pytest.mark.asyncio
async def test_send_log_only_includes_recipient_and_subject(
    email_service: EmailService,
) -> None:
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch("src.services.email_service.logger") as mock_logger,
    ):
        mock_settings.EMAIL_LOG_ONLY = True
        await email_service._send("me@co.com", "Hello", "body", "<p>html</p>")

    call_args = mock_logger.info.call_args[0]
    assert "me@co.com" in str(call_args)
    assert "Hello" in str(call_args)


# ── SMTP failure tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_smtp_failure_caught_and_logged_not_raised(
    email_service: EmailService,
) -> None:
    """SMTP errors must be caught, logged, and NOT re-raised."""
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch("src.services.email_service.logger") as mock_logger,
        patch.object(
            email_service,
            "_send_sync",
            side_effect=ConnectionRefusedError("SMTP down"),
        ),
    ):
        mock_settings.EMAIL_LOG_ONLY = False
        mock_settings.SMTP_FROM = "noreply@test.com"

        # Must NOT raise
        await email_service._send("a@b.com", "sub", "txt", "<p>h</p>")

    mock_logger.error.assert_called_once()
    error_msg = mock_logger.error.call_args[0][0]
    assert "failed" in error_msg.lower() or "Failed" in error_msg


@pytest.mark.asyncio
async def test_smtp_timeout_caught_and_logged(
    email_service: EmailService,
) -> None:
    """Timeout during SMTP must be caught."""
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch("src.services.email_service.logger") as mock_logger,
        patch.object(
            email_service,
            "_send_sync",
            side_effect=TimeoutError("SMTP timeout"),
        ),
    ):
        mock_settings.EMAIL_LOG_ONLY = False
        mock_settings.SMTP_FROM = "noreply@test.com"

        await email_service._send("x@y.com", "s", "t", "<p>h</p>")

    mock_logger.error.assert_called_once()


# ── Thread-pool executor tests ────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_uses_executor_for_smtp_call(
    email_service: EmailService,
) -> None:
    """_send must call _send_sync via run_in_executor when not in log-only mode."""
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch("asyncio.get_running_loop") as mock_get_loop,
    ):
        mock_settings.EMAIL_LOG_ONLY = False
        mock_settings.SMTP_FROM = "noreply@test.com"
        mock_loop = MagicMock()
        future = asyncio.Future()
        future.set_result(None)
        mock_loop.run_in_executor.return_value = future
        mock_get_loop.return_value = mock_loop

        await email_service._send("a@b.com", "subj", "txt", "<p>h</p>")

    mock_loop.run_in_executor.assert_called_once()
    executor_args = mock_loop.run_in_executor.call_args[0]
    assert executor_args[0] is None  # default executor
    assert executor_args[1] == email_service._send_sync


# ── _send_sync SMTP tests ────────────────────────────────────────────

def test_send_sync_with_tls(email_service: EmailService) -> None:
    """_send_sync must call starttls() when SMTP_USE_TLS is True."""
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch("src.services.email_service.smtplib.SMTP") as mock_smtp_cls,
    ):
        mock_settings.SMTP_HOST = "mail.test.com"
        mock_settings.SMTP_PORT = 587
        mock_settings.SMTP_USE_TLS = True
        mock_settings.SMTP_USER = "user"
        mock_settings.SMTP_PASSWORD = "pass"
        mock_settings.SMTP_FROM = "from@test.com"

        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        msg = MIMEMultipart()
        msg["To"] = "to@test.com"
        email_service._send_sync("to@test.com", msg)

    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("user", "pass")
    mock_server.sendmail.assert_called_once()
    mock_server.quit.assert_called_once()


def test_send_sync_without_tls(email_service: EmailService) -> None:
    """_send_sync must NOT call starttls() when SMTP_USE_TLS is False."""
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch("src.services.email_service.smtplib.SMTP") as mock_smtp_cls,
    ):
        mock_settings.SMTP_HOST = "mail.test.com"
        mock_settings.SMTP_PORT = 25
        mock_settings.SMTP_USE_TLS = False
        mock_settings.SMTP_USER = None
        mock_settings.SMTP_PASSWORD = None
        mock_settings.SMTP_FROM = "from@test.com"

        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        msg = MIMEMultipart()
        email_service._send_sync("to@t.com", msg)

    mock_server.starttls.assert_not_called()
    mock_server.login.assert_not_called()
    mock_server.sendmail.assert_called_once()
    mock_server.quit.assert_called_once()


def test_send_sync_without_credentials(email_service: EmailService) -> None:
    """No login attempt when SMTP_USER/SMTP_PASSWORD are None."""
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch("src.services.email_service.smtplib.SMTP") as mock_smtp_cls,
    ):
        mock_settings.SMTP_HOST = "mail.test.com"
        mock_settings.SMTP_PORT = 587
        mock_settings.SMTP_USE_TLS = True
        mock_settings.SMTP_USER = None
        mock_settings.SMTP_PASSWORD = None
        mock_settings.SMTP_FROM = "from@test.com"

        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        msg = MIMEMultipart()
        email_service._send_sync("to@t.com", msg)

    mock_server.login.assert_not_called()


# ── Integration-style: full path invitation (log-only) ───────────────

@pytest.mark.asyncio
async def test_send_invitation_end_to_end_log_only(
    email_service: EmailService,
) -> None:
    """Full call path for invitation in log-only mode."""
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch("src.services.email_service.logger") as mock_logger,
    ):
        mock_settings.EMAIL_LOG_ONLY = True
        mock_settings.FRONTEND_URL = "http://localhost:3000"

        await email_service.send_invitation("new@co.com", "ABC123")

    mock_logger.info.assert_called_once()
    log_body = str(mock_logger.info.call_args)
    assert "http://localhost:3000/auth/setup?token=ABC123" in log_body


@pytest.mark.asyncio
async def test_send_password_reset_end_to_end_log_only(
    email_service: EmailService,
) -> None:
    """Full call path for password-reset in log-only mode."""
    with (
        patch("src.services.email_service.settings") as mock_settings,
        patch("src.services.email_service.logger") as mock_logger,
    ):
        mock_settings.EMAIL_LOG_ONLY = True
        mock_settings.FRONTEND_URL = "http://localhost:3000"

        await email_service.send_password_reset("user@co.com", "RST-999")

    mock_logger.info.assert_called_once()
    log_body = str(mock_logger.info.call_args)
    assert "http://localhost:3000/auth/password-reset/confirm?token=RST-999" in log_body
