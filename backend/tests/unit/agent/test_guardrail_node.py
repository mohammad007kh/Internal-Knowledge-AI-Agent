"""Unit tests for the guardrail LangGraph nodes."""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

from unittest.mock import AsyncMock, MagicMock  # noqa: E402

import pytest  # noqa: E402

from src.agent.nodes.guardrail import guardrail_output  # noqa: E402


@pytest.fixture()
def base_state() -> dict[str, object]:
    return {
        "session_id": "00000000-0000-0000-0000-000000000010",
        "user_id": "00000000-0000-0000-0000-000000000001",
        "trace_id": "trace-1",
        "query": "What is our refund policy?",
        "final_answer": None,
        "error": None,
    }


@pytest.fixture()
def mock_guardrail_service() -> MagicMock:
    """Service should NOT be called when answer is empty."""
    svc = MagicMock()
    svc.evaluate_output = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_guardrail_output_empty_answer_returns_fallback(
    base_state: dict[str, object],
    mock_guardrail_service: MagicMock,
) -> None:
    """When pipeline reaches the output guard with empty final_answer, the
    node MUST substitute a non-empty fallback so the API persist path doesn't
    crash on the NOT NULL ``content`` column.
    """
    base_state["final_answer"] = None

    result = await guardrail_output(
        base_state,  # type: ignore[arg-type]
        guardrail_service=mock_guardrail_service,
        ai_model_resolver=None,
    )

    # No upstream evaluation — we short-circuit with a fallback string.
    mock_guardrail_service.evaluate_output.assert_not_awaited()

    # Invariant: pipeline must exit with a non-empty final_answer.
    assert "final_answer" in result
    fallback = result["final_answer"]
    assert isinstance(fallback, str)
    assert len(fallback.strip()) > 0


@pytest.mark.asyncio
async def test_guardrail_output_empty_string_answer_returns_fallback(
    base_state: dict[str, object],
    mock_guardrail_service: MagicMock,
) -> None:
    """An empty string is just as bad as None — both must trip the fallback."""
    base_state["final_answer"] = ""

    result = await guardrail_output(
        base_state,  # type: ignore[arg-type]
        guardrail_service=mock_guardrail_service,
        ai_model_resolver=None,
    )

    mock_guardrail_service.evaluate_output.assert_not_awaited()
    assert result.get("final_answer", "")
    assert len(result["final_answer"].strip()) > 0
