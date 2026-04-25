"""Audit service — emits append-only ``admin_audit_log`` rows.

Provides :func:`emit_audit`, a thin convenience helper that resolves the
admin user / IP from the FastAPI :class:`~fastapi.Request` and writes a
single row.  Callers MUST never include API keys in *metadata*.
"""

from __future__ import annotations

import ipaddress
import logging
import uuid
from typing import Any

from fastapi import Request

from src.repositories.admin_audit_log_repository import AdminAuditLogRepository

logger = logging.getLogger(__name__)


_REDACTED_KEYS = frozenset({"api_key", "api_key_encrypted", "password", "secret"})


def _client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    candidate = request.client.host
    if not candidate:
        return None
    # Validate before passing into INET column to avoid SQL errors.
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return candidate


def _redact(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return *metadata* with redacted-key entries stripped, recursively.

    Walks nested dicts and list-of-dicts so deeply-buried secrets — e.g.
    ``{"items": [{"api_key": "sk-…"}]}`` — never reach the audit log.
    """
    if not metadata:
        return {}
    return _redact_value(metadata)  # type: ignore[return-value]


def _redact_value(value: Any) -> Any:
    """Recursively strip redacted keys from nested structures."""
    if isinstance(value, dict):
        return {
            k: _redact_value(v)
            for k, v in value.items()
            if k.lower() not in _REDACTED_KEYS
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    return value


async def emit_audit(
    repo: AdminAuditLogRepository,
    *,
    admin_user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None,
    request: Request | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Persist a single audit-log row.

    Errors are logged but never re-raised — auditing must not break the
    primary action.
    """
    safe_metadata = _redact(metadata)
    try:
        await repo.insert(
            admin_user_id=admin_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=_client_ip(request),
            metadata=safe_metadata,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "audit-log insert failed: action=%s resource=%s id=%s",
            action,
            resource_type,
            resource_id,
        )
