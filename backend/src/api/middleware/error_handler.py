from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


def _internal_error_response(instance: str) -> JSONResponse:
    """The single canonical 500 envelope — never echoes ``str(exc)``."""
    return _problem_response(
        type_="internal_error",
        title="Internal Server Error",
        status=500,
        detail="An unexpected error occurred.",
        instance=instance,
    )


class InnerServerErrorMiddleware:
    """ASGI middleware that converts any unhandled exception into a clean 500.

    *Why this exists in addition to the ``@app.exception_handler(Exception)``
    registration below:* Starlette/FastAPI route an ``Exception`` (or ``500``)
    handler onto the **outermost** ``ServerErrorMiddleware`` — which sits
    *outside* every user middleware, including ``CORSMiddleware``.  A 500
    emitted there is written straight to the raw ASGI ``send`` and therefore
    never picks up the ``Access-Control-Allow-Origin`` header, so browsers
    surface it as a CORS failure rather than a readable error.

    This middleware is registered via :func:`register_exception_handlers`
    *before* the other ``app.add_middleware`` calls in ``create_app`` — so it
    ends up as the **innermost** user middleware (just outside
    ``ExceptionMiddleware``).  When the route (or anything inside it) raises an
    exception that no specific handler claimed, this catches it and emits the
    standard ``application/problem+json`` 500; that response then flows back
    out through ``CORSMiddleware`` (and the security-headers / request-id
    middleware) and *does* get the CORS headers.

    The traceback / ``str(exc)`` is logged server-side only — never echoed in
    the response body.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def _send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception:  # noqa: BLE001 — last line of defence inside CORS
            path = scope.get("path", "")
            logger.exception("Unhandled error on [%s]", path)
            if response_started:
                # The downstream app already started streaming a response — we
                # can't replace it.  Re-raise so ServerErrorMiddleware logs it.
                raise
            await _internal_error_response(str(path))(scope, receive, send)


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the app.  Call from create_app().

    Also installs :class:`InnerServerErrorMiddleware`.  Because this runs
    before the other ``app.add_middleware`` calls in ``create_app``, that
    middleware ends up *innermost* among the user middleware — inside
    ``CORSMiddleware`` — which is exactly what makes unhandled-error 500s
    carry the CORS headers (see the class docstring).
    """

    app.add_middleware(InnerServerErrorMiddleware)

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

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Last-resort catch-all (runs on the outermost ``ServerErrorMiddleware``).

        :class:`InnerServerErrorMiddleware` already converts unhandled
        exceptions raised by the *route* into a CORS-decorated 500.  This
        handler covers the residual case: an exception raised by one of the
        outer user middleware themselves (CORS / security-headers / rate-limit
        / request-id), which never reaches the inner middleware.  Such a
        response still cannot carry CORS headers (the bug lives in the very
        layer that would add them), but it is at least the standard
        ``application/problem+json`` envelope rather than plain text — and the
        traceback / ``str(exc)`` is logged server-side only, never echoed.
        """
        logger.exception("Unhandled error on [%s]", request.url.path)
        return _internal_error_response(str(request.url.path))
