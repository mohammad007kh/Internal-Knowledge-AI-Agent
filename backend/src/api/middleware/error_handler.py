from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.core.exceptions import AppError

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)
_PROBLEM_CONTENT_TYPE = "application/problem+json"


def _sanitize_validation_errors(errors: Sequence[Any]) -> list[Any]:
    """Convert non-JSON-serializable Exception objects in Pydantic v2 ctx to strings."""
    sanitized = []
    for err in errors:
        e = dict(err)
        if "ctx" in e and isinstance(e["ctx"], dict):
            e["ctx"] = {
                k: str(v) if isinstance(v, Exception) else v
                for k, v in e["ctx"].items()
            }
        sanitized.append(e)
    return sanitized


def _problem_response(
    *,
    type_: str,
    title: str,
    status: int,
    detail: str,
    instance: str,
    extra: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": f"https://knowledge-agent.internal/errors/{type_}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
    }
    if extra:
        body["extra"] = extra
    response_headers = {"Content-Type": _PROBLEM_CONTENT_TYPE}
    if headers:
        response_headers.update(headers)
    return JSONResponse(
        content=body,
        status_code=status,
        headers=response_headers,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the app.  Call from create_app()."""

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        # Log 5xx as ERROR, 4xx as WARNING
        if exc.status_code >= 500:
            logger.error("AppError [%s]: %s", exc.error_type, exc.detail, exc_info=exc)
        else:
            logger.warning("AppError [%s]: %s", exc.error_type, exc.detail)

        # Surface Retry-After when the error carries one (e.g. 423 lockout).
        extra_headers: dict[str, str] | None = None
        retry_after = (exc.extra or {}).get("retry_after_seconds")
        if isinstance(retry_after, int) and retry_after > 0:
            extra_headers = {"Retry-After": str(retry_after)}

        return _problem_response(
            type_=exc.error_type,
            title=exc.title,
            status=exc.status_code,
            detail=exc.detail,
            instance=str(request.url.path),
            extra=exc.extra or None,
            headers=extra_headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning("Validation error on [%s]: %s", request.url.path, exc.errors())
        return _problem_response(
            type_="validation_error",
            title="Validation Error",
            status=422,
            detail="Request body or parameters failed validation.",
            instance=str(request.url.path),
            extra={"errors": _sanitize_validation_errors(exc.errors())},
        )

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
        return _problem_response(
            type_="not_found",
            title="Not Found",
            status=404,
            detail=f"The requested resource '{request.url.path}' was not found.",
            instance=str(request.url.path),
        )

    @app.exception_handler(405)
    async def method_not_allowed_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return _problem_response(
            type_="method_not_allowed",
            title="Method Not Allowed",
            status=405,
            detail=f"Method '{request.method}' is not allowed for '{request.url.path}'.",
            instance=str(request.url.path),
        )
