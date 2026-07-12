from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, EmailStr

from src.api.middleware.error_handler import register_exception_handlers
from src.core.exceptions import NotFoundError


def _make_app() -> FastAPI:
    """A minimal FastAPI app wired with the RFC7807 error handlers.

    Mirrors the established unit-test pattern (see
    ``tests/unit/api/middleware/test_error_handler.py``): build a bare app,
    call ``register_exception_handlers`` and mount a few local routes so the
    handlers can be exercised without a database, Redis, or MinIO.
    """
    app = FastAPI()
    register_exception_handlers(app)

    router = APIRouter(prefix="/api/v1")

    @router.get("/_test/not-found")
    async def _raise_not_found() -> dict[str, str]:
        # Exercises the AppError handler (NotFoundError -> 404 problem+json).
        raise NotFoundError("resource missing")

    class _LoginBody(BaseModel):
        email: EmailStr
        password: str

    @router.post("/auth/login")
    async def _login(body: _LoginBody) -> dict[str, str]:
        # A body-validated route so a garbage payload triggers
        # RequestValidationError (422 problem+json with extra.errors).
        return {"email": body.email}

    app.include_router(router)
    return app


@pytest_asyncio.fixture()
async def client() -> AsyncIterator[AsyncClient]:
    """HTTPX async client bound to a DB-free app with the error handlers.

    The shared ``client`` fixture in ``tests/conftest.py`` only exists when
    ``RUN_INTEGRATION_TESTS=1`` and is wired to a live test database; these are
    pure unit tests of the error envelope, so they get their own lightweight
    in-process client (ASGITransport, no network, no DB).
    """
    app = _make_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_unknown_route_returns_404_problem_json(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    ct = response.headers["content-type"]
    assert "application/problem+json" in ct
    body = response.json()
    assert body["status"] == 404
    assert "type" in body
    assert "title" in body
    assert "detail" in body
    assert "instance" in body


@pytest.mark.asyncio
async def test_app_error_returns_problem_json(client: AsyncClient) -> None:
    # A test route that raises NotFoundError (added only in test configuration)
    response = await client.get("/api/v1/_test/not-found")
    assert response.status_code == 404
    body = response.json()
    assert body["type"].endswith("not_found")


@pytest.mark.asyncio
async def test_validation_error_returns_422_problem_json(client: AsyncClient) -> None:
    # POST to any endpoint that expects a body; send garbage JSON
    response = await client.post(
        "/api/v1/auth/login",
        json={"not_email": "bad"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["status"] == 422
    assert "errors" in body.get("extra", {})
