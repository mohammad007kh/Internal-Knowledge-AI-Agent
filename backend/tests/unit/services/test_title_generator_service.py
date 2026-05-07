"""Unit tests for TitleGeneratorService — auto-title chat sessions."""
from __future__ import annotations

import asyncio
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# Match the env-bootstrap pattern used by other unit tests so importing the
# service does not pull in real Settings validation.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

from src.services.title_generator import (  # noqa: E402
    TitleGeneratorService,
    _normalise_title,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chat_completion(content: str | None) -> MagicMock:
    """Build the minimal AsyncOpenAI-shaped response the service consumes."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_resolver(
    *,
    chat_response: Any = None,
    chat_side_effect: Exception | None = None,
    custom_prompt: str | None = None,
) -> AsyncMock:
    """Mock AIModelResolver returning a fake AIModelClient with a stub OpenAI client."""
    http_client = MagicMock()
    create = AsyncMock()
    if chat_side_effect is not None:
        create.side_effect = chat_side_effect
    else:
        create.return_value = chat_response
    http_client.chat.completions.create = create

    client = MagicMock()
    client.model_id = "gpt-4o-mini"
    client.provider = "openai"
    client.temperature = 0.3
    client.max_tokens = 30
    client.custom_prompt = custom_prompt
    client.http_client = http_client

    resolver = AsyncMock()
    resolver.resolve = AsyncMock(return_value=client)
    # Expose the inner mocks so tests can assert on them.
    resolver._http_client = http_client
    resolver._create = create
    return resolver


# ---------------------------------------------------------------------------
# Pure-function tests for _normalise_title
# ---------------------------------------------------------------------------


class TestNormaliseTitle:
    def test_strips_surrounding_double_quotes(self) -> None:
        assert _normalise_title('"Mohammad CV"') == "Mohammad CV"

    def test_strips_surrounding_single_quotes(self) -> None:
        assert _normalise_title("'Mohammad CV'") == "Mohammad CV"

    def test_strips_trailing_period(self) -> None:
        assert _normalise_title("Q3 EMEA sales growth.") == "Q3 EMEA sales growth"

    def test_drops_title_prefix(self) -> None:
        assert _normalise_title("Title: Mohammad CV") == "Mohammad CV"

    def test_caps_at_60_chars(self) -> None:
        long = "A" * 200
        out = _normalise_title(long)
        assert out is not None
        assert len(out) == 60

    def test_empty_input_returns_none(self) -> None:
        assert _normalise_title("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert _normalise_title("   \n\t  ") is None

    def test_only_punctuation_returns_none(self) -> None:
        assert _normalise_title("\"'.!?") is None


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


class TestGenerateTitle:
    """End-to-end behaviour of TitleGeneratorService.generate_title."""

    async def test_happy_path_returns_trimmed_string(self) -> None:
        resolver = _make_resolver(
            chat_response=_make_chat_completion("  Mohammad's research interests  ")
        )
        svc = TitleGeneratorService(ai_model_resolver=resolver)

        result = await svc.generate_title("Tell me about Mohammad's research")

        assert result == "Mohammad's research interests"
        resolver._create.assert_awaited_once()

    async def test_quote_stripping(self) -> None:
        resolver = _make_resolver(
            chat_response=_make_chat_completion('"Mohammad CV"')
        )
        svc = TitleGeneratorService(ai_model_resolver=resolver)

        assert await svc.generate_title("hi") == "Mohammad CV"

    async def test_caps_long_output_at_60_chars(self) -> None:
        resolver = _make_resolver(
            chat_response=_make_chat_completion("A" * 100)
        )
        svc = TitleGeneratorService(ai_model_resolver=resolver)

        result = await svc.generate_title("hi")

        assert result is not None
        assert len(result) == 60

    async def test_timeout_returns_none(self) -> None:
        async def _slow_resolve(_stage: str) -> Any:
            await asyncio.sleep(5.0)  # well past the 0.05 s test timeout
            return MagicMock()

        resolver = AsyncMock()
        resolver.resolve = _slow_resolve
        svc = TitleGeneratorService(ai_model_resolver=resolver)

        result = await svc.generate_title("hi", timeout_s=0.05)

        assert result is None

    async def test_llm_exception_returns_none(self) -> None:
        resolver = _make_resolver(
            chat_side_effect=RuntimeError("openai exploded")
        )
        svc = TitleGeneratorService(ai_model_resolver=resolver)

        assert await svc.generate_title("hi") is None

    async def test_empty_llm_output_returns_none(self) -> None:
        resolver = _make_resolver(chat_response=_make_chat_completion(""))
        svc = TitleGeneratorService(ai_model_resolver=resolver)

        assert await svc.generate_title("hi") is None

    async def test_whitespace_llm_output_returns_none(self) -> None:
        resolver = _make_resolver(chat_response=_make_chat_completion("   \n  "))
        svc = TitleGeneratorService(ai_model_resolver=resolver)

        assert await svc.generate_title("hi") is None

    async def test_none_llm_content_returns_none(self) -> None:
        resolver = _make_resolver(chat_response=_make_chat_completion(None))
        svc = TitleGeneratorService(ai_model_resolver=resolver)

        assert await svc.generate_title("hi") is None

    async def test_blank_user_message_short_circuits(self) -> None:
        resolver = _make_resolver(chat_response=_make_chat_completion("ignored"))
        svc = TitleGeneratorService(ai_model_resolver=resolver)

        assert await svc.generate_title("   ") is None
        resolver.resolve.assert_not_awaited()

    async def test_resolver_failure_returns_none(self) -> None:
        resolver = AsyncMock()
        resolver.resolve = AsyncMock(side_effect=RuntimeError("no titler stage"))
        svc = TitleGeneratorService(ai_model_resolver=resolver)

        assert await svc.generate_title("hi") is None

    async def test_uses_custom_prompt_when_provided(self) -> None:
        custom = "Custom titler prompt for tests"
        resolver = _make_resolver(
            chat_response=_make_chat_completion("Test title"),
            custom_prompt=custom,
        )
        svc = TitleGeneratorService(ai_model_resolver=resolver)

        result = await svc.generate_title("hi")

        assert result == "Test title"
        # Verify the system prompt sent to the LLM is the admin override.
        call_kwargs = resolver._create.call_args.kwargs
        messages = call_kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == custom


# ---------------------------------------------------------------------------
# Pytest config — no asyncio markers needed since pyproject sets auto mode.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _silence_warnings(caplog: pytest.LogCaptureFixture) -> None:
    """Pre-set caplog level so WARNING failures don't pollute test output."""
    caplog.set_level("ERROR")
