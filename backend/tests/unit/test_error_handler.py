import pytest
from httpx import AsyncClient


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
