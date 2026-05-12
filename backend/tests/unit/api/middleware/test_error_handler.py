"""Unit tests for ``register_exception_handlers`` — the API error envelope.

Focus: the catch-all ``Exception`` handler (the fix for the "500s bypass
CORS" symptom).  Because the handler is registered on the app's
``ExceptionMiddleware`` — which sits *inside* ``CORSMiddleware`` in the stack
— its 500 response is wrapped by ``CORSMiddleware`` and therefore carries the
``Access-Control-Allow-Origin`` header.  Without the handler the exception
escaped to Starlette's outermost ``ServerErrorMiddleware`` (outside CORS),
whose bare 500 had no CORS headers, so the browser reported a CORS failure.

We assert:
  * an endpoint that raises a bare ``RuntimeError`` → 500 with the
    ``application/problem+json`` envelope (``status: 500``).
  * the response body never leaks ``str(exc)`` / a traceback.
  * the 500 still flows back out through ``CORSMiddleware`` (the
    ``Access-Control-Allow-Origin`` header is present).
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from src.api.middleware.error_handler import register_exception_handlers

_SECRET_MARKER = "super-secret-internal-detail-do-not-leak"


def _make_app(*, with_cors: bool = False) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    router = APIRouter()

    @router.get("/boom")
    async def _boom() -> dict[str, str]:
        # A bare unhandled exception — must not be a subclass of AppError /
        # HTTPException, so it bubbles past ExceptionMiddleware.
        raise RuntimeError(_SECRET_MARKER)

    @router.get("/ok")
    async def _ok() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(router)

    if with_cors:
        # Mirror src/main.py: CORSMiddleware is added LAST so it ends up the
        # outermost user middleware — it must wrap the 500 emitted by
        # InnerServerErrorMiddleware (which register_exception_handlers
        # installs as the innermost user middleware).
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:3000"],
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization"],
        )
    return app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(_make_app(), raise_server_exceptions=False)


@pytest.fixture()
def cors_client() -> TestClient:
    return TestClient(_make_app(with_cors=True), raise_server_exceptions=False)


class TestUnhandledExceptionHandler:
    def test_bare_runtimeerror_returns_problem_json_500(self, client: TestClient) -> None:
        resp = client.get("/boom")

        assert resp.status_code == 500
        assert resp.headers["content-type"].startswith("application/problem+json")
        body = resp.json()
        assert body["status"] == 500
        assert body["title"] == "Internal Server Error"
        assert body["type"].endswith("/errors/internal_error")
        assert body["instance"] == "/boom"
        assert body["detail"] == "An unexpected error occurred."

    def test_response_body_does_not_leak_exception_text(self, client: TestClient) -> None:
        resp = client.get("/boom")

        assert resp.status_code == 500
        raw = resp.text
        assert _SECRET_MARKER not in raw
        # No traceback / exception-class noise either.
        assert "RuntimeError" not in raw
        assert "Traceback" not in raw

    def test_500_carries_cors_header_when_wrapped_by_cors_middleware(
        self, cors_client: TestClient
    ) -> None:
        resp = cors_client.get("/boom", headers={"Origin": "http://localhost:3000"})

        assert resp.status_code == 500
        # The whole point: the error response flows back out through
        # CORSMiddleware, so the browser can actually read it.
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"

    def test_healthy_route_still_works(self, client: TestClient) -> None:
        resp = client.get("/ok")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
