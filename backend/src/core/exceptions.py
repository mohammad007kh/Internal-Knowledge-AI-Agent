from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base application error. All sub-classes map to HTTP problem details."""

    status_code: int = 500
    error_type: str = "internal_error"
    title: str = "Internal Server Error"

    def __init__(
        self,
        detail: str = "An unexpected error occurred.",
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.extra = extra or {}


class BadRequestError(AppError):
    status_code = 400
    error_type = "bad_request"
    title = "Bad Request"


class UnauthorizedError(AppError):
    status_code = 401
    error_type = "unauthorized"
    title = "Unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    error_type = "forbidden"
    title = "Forbidden"


class NotFoundError(AppError):
    status_code = 404
    error_type = "not_found"
    title = "Not Found"


class ConflictError(AppError):
    status_code = 409
    error_type = "conflict"
    title = "Conflict"


class UnprocessableError(AppError):
    """Semantic validation failure (distinct from 422 schema errors)."""

    status_code = 422
    error_type = "unprocessable"
    title = "Unprocessable Entity"


class InternalError(AppError):
    status_code = 500
    error_type = "internal_error"
    title = "Internal Server Error"


class ValidationError(AppError):
    """Business-rule validation failure (e.g. expired token)."""

    status_code = 422
    error_type = "validation_error"
    title = "Validation Error"


class ServiceUnavailableError(AppError):
    status_code = 503
    error_type = "service_unavailable"
    title = "Service Unavailable"


class AccountLockedError(AppError):
    """Raised when an account is locked due to repeated failed login attempts.

    Maps to HTTP 423 Locked. The handler attaches a ``Retry-After`` header
    derived from ``extra["retry_after_seconds"]`` when present.
    """

    status_code = 423
    error_type = "account_locked"
    title = "Account Locked"


class RedisUnavailableError(AppError):
    """Raised when Redis is required but unreachable (fail-closed lockout)."""

    status_code = 503
    error_type = "redis_unavailable"
    title = "Service Unavailable"


class EmbeddingDimensionError(ValueError):
    """Raised when an embedding vector has an unexpected number of dimensions."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(
            f"Expected embedding dimension {expected}, got {actual}"
        )
        self.expected = expected
        self.actual = actual
