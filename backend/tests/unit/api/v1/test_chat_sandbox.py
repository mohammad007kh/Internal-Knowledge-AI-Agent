"""Unit tests for ``POST /chat/sandbox/stream`` — Slice A.

The sandbox endpoint runs the agent pipeline against ONE source so admins
can debug retrieval failures without polluting chat_sessions /
chat_messages with throwaway runs. Tests assert:

* admin-only auth (403 for non-admin),
* 404 when the source does not exist,
* SSE event grammar matches the session-chat endpoint (delta + done),
* nothing is persisted to chat_sessions / chat_messages,
* exactly one ``admin_audit_log`` row is emitted.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.middleware.error_handler import register_exception_handlers  # noqa: E402
from src.api.v1.chat import (  # noqa: E402
    _get_agentic_pipeline_provider,
    _get_chat_message_repo,
    _get_chat_session_repo,
    _get_chat_session_service,
    _get_db_session_factory,
    _get_pipeline_provider,
    _get_title_generator,
    _get_tracing,
    router,
)
from src.core.database import get_db  # noqa: E402
from src.core.deps import get_current_user  # noqa: E402
from src.models.user import User, UserRole  # noqa: E402

ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
SOURCE_ID = uuid.UUID("00000000-0000-0000-0000-000000000033")
TRACE_ID = "trace-sandbox-1"


def _make_user(role: UserRole, user_id: uuid.UUID) -> User:
    u = MagicMock(spec=User)
    u.id = user_id
    u.email = f"{role.value}@example.com"
    u.role = role
    u.is_active = True
    return u


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def admin_user() -> User:
    return _make_user(UserRole.admin, ADMIN_ID)


@pytest.fixture()
def regular_user() -> User:
    return _make_user(UserRole.user, USER_ID)


@pytest.fixture()
def db() -> MagicMock:
    """Stand-in for the request-scoped AsyncSession.

    Mixes sync and async attributes — :meth:`AsyncSession.add` is sync on the
    real class, so we use a :class:`MagicMock` base and attach
    :class:`AsyncMock` to the awaitable methods explicitly. That keeps
    ``await db.scalar(...)`` / ``await db.commit()`` working while leaving
    ``db.add(row)`` non-awaitable so we can assert on its call count
    without "coroutine never awaited" warnings.
    """
    mock = MagicMock()
    src = MagicMock()
    src.id = SOURCE_ID
    src.is_active = True
    src.deleted_at = None
    mock.scalar = AsyncMock(return_value=src)
    mock.commit = AsyncMock()
    mock.flush = AsyncMock()
    mock.execute = AsyncMock()
    mock.add = MagicMock()  # sync — mirrors real AsyncSession contract
    return mock


@pytest.fixture()
def mock_pipeline() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def mock_tracing() -> MagicMock:
    t = MagicMock()
    t.start_trace.return_value = TRACE_ID
    return t


def _make_db_factory(db_mock: MagicMock) -> MagicMock:
    """Async-context-manager factory yielding the same db mock on every call."""

    @asynccontextmanager
    async def _ctx():  # type: ignore[no-untyped-def]
        yield db_mock

    factory = MagicMock()
    factory.side_effect = lambda: _ctx()
    return factory


@pytest.fixture()
def app(
    admin_user: User,
    db: MagicMock,
    mock_pipeline: AsyncMock,
    mock_tracing: MagicMock,
) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/chat")

    # Default to admin auth — tests that need a non-admin override later.
    app.dependency_overrides[get_current_user] = lambda: admin_user
    app.dependency_overrides[get_db] = lambda: db
    # The endpoints now depend on a pipeline PROVIDER (a call-time factory) that
    # `_scoped_pipeline` invokes with the scoped session kwargs (#276). Override
    # with a fake provider that ignores those kwargs and returns the mock.
    app.dependency_overrides[_get_pipeline_provider] = lambda: (
        lambda **_kw: mock_pipeline
    )
    # T-058: the sandbox endpoint resolves the sandbox-first agentic pipeline.
    # Override both so the same mock drives the stream regardless of which
    # provider the endpoint depends on.
    app.dependency_overrides[_get_agentic_pipeline_provider] = lambda: (
        lambda **_kw: mock_pipeline
    )
    app.dependency_overrides[_get_tracing] = lambda: mock_tracing
    # Plumb the unrelated chat deps to no-op mocks so the router instantiates.
    app.dependency_overrides[_get_db_session_factory] = lambda: _make_db_factory(db)
    app.dependency_overrides[_get_chat_session_repo] = lambda: AsyncMock()
    app.dependency_overrides[_get_chat_message_repo] = lambda: AsyncMock()
    app.dependency_overrides[_get_chat_session_service] = lambda: AsyncMock()
    app.dependency_overrides[_get_title_generator] = lambda: AsyncMock()
    return app


@pytest.fixture()
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


# ---------------------------------------------------------------------------
# Pipeline event helpers (mirror test_chat_router.py)
# ---------------------------------------------------------------------------


def _delta_event(text: str) -> dict[str, Any]:
    chunk = MagicMock()
    chunk.content = text
    return {
        "event": "on_chat_model_stream",
        "data": {"chunk": chunk},
        "name": "ChatModel",
    }


def _chain_end_event(final_answer: str) -> dict[str, Any]:
    return {
        "event": "on_chain_end",
        "name": "LangGraph",
        "data": {"output": {"final_answer": final_answer, "sources": []}},
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSandboxAuth:
    """Admin-only — non-admin users get 403 before the pipeline even starts."""

    def test_non_admin_403(
        self,
        app: FastAPI,
        client: TestClient,
        regular_user: User,
        mock_pipeline: AsyncMock,
    ) -> None:
        app.dependency_overrides[get_current_user] = lambda: regular_user

        resp = client.post(
            "/chat/sandbox/stream",
            json={"source_id": str(SOURCE_ID), "query": "hello"},
        )

        assert resp.status_code == 403
        # Pipeline must NOT have been driven for an unauthorised caller.
        mock_pipeline.astream_events.assert_not_called()

    def test_admin_passes_auth(
        self,
        client: TestClient,
        mock_pipeline: AsyncMock,
    ) -> None:
        async def _events(*_a: Any, **_kw: Any) -> AsyncGenerator[dict[str, Any], None]:
            yield _delta_event("hi")
            yield _chain_end_event("hi")

        mock_pipeline.astream_events = _events

        resp = client.post(
            "/chat/sandbox/stream",
            json={"source_id": str(SOURCE_ID), "query": "hello"},
        )
        assert resp.status_code == 200


class TestSandboxNotFound:
    """A non-existent or soft-deleted source returns 404 (not 500)."""

    def test_missing_source_404(
        self,
        client: TestClient,
        db: MagicMock,
    ) -> None:
        db.scalar = AsyncMock(return_value=None)

        resp = client.post(
            "/chat/sandbox/stream",
            json={"source_id": str(SOURCE_ID), "query": "anything"},
        )
        assert resp.status_code == 404


class TestSandboxStreaming:
    """SSE event grammar must match the session-chat endpoint byte-for-byte."""

    def test_streams_delta_and_done(
        self,
        client: TestClient,
        mock_pipeline: AsyncMock,
    ) -> None:
        async def _events(*_a: Any, **_kw: Any) -> AsyncGenerator[dict[str, Any], None]:
            yield _delta_event("Hello")
            yield _delta_event(" world")
            yield _chain_end_event("Hello world")

        mock_pipeline.astream_events = _events

        resp = client.post(
            "/chat/sandbox/stream",
            json={"source_id": str(SOURCE_ID), "query": "say hi"},
        )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        # Both delta tokens shipped in order. Don't lock exact whitespace
        # in the JSON body — json.dumps default separators may shift between
        # Python releases — but the token strings themselves are stable.
        assert "event: delta" in body
        assert "Hello" in body
        assert "world" in body
        # Terminal done frame with the sandbox sentinel session id.
        assert "event: done" in body
        assert "__sandbox__" in body

    def test_pipeline_error_yields_error_frame(
        self,
        client: TestClient,
        mock_pipeline: AsyncMock,
    ) -> None:
        async def _failing_events(
            *_a: Any, **_kw: Any
        ) -> AsyncGenerator[dict[str, Any], None]:
            raise RuntimeError("boom")
            yield  # pragma: no cover — keeps this an async generator

        mock_pipeline.astream_events = _failing_events

        resp = client.post(
            "/chat/sandbox/stream",
            json={"source_id": str(SOURCE_ID), "query": "explode"},
        )
        assert resp.status_code == 200
        assert "event: error" in resp.text
        assert "pipeline_error" in resp.text


class TestSandboxNoPersistence:
    """Sandbox MUST NOT touch chat_sessions / chat_messages / message_feedback.

    The endpoint deliberately doesn't depend on the chat-message or chat-session
    repos — calling either would mean we wired persistence by accident. We
    assert their mocks were never awaited.
    """

    def test_no_chat_message_create(
        self,
        app: FastAPI,
        client: TestClient,
        mock_pipeline: AsyncMock,
    ) -> None:
        # Replace the message repo with a tracking AsyncMock and assert it
        # was never used.
        msg_repo = AsyncMock()
        app.dependency_overrides[_get_chat_message_repo] = lambda: msg_repo

        async def _events(*_a: Any, **_kw: Any) -> AsyncGenerator[dict[str, Any], None]:
            yield _delta_event("ok")
            yield _chain_end_event("ok")

        mock_pipeline.astream_events = _events

        resp = client.post(
            "/chat/sandbox/stream",
            json={"source_id": str(SOURCE_ID), "query": "no persist"},
        )
        assert resp.status_code == 200

        # No chat_messages writes — sandbox is ephemeral.
        msg_repo.create.assert_not_awaited()

    def test_audit_row_emitted_once(
        self,
        client: TestClient,
        mock_pipeline: AsyncMock,
        db: MagicMock,
    ) -> None:
        """Exactly one ``admin_audit_log`` row per sandbox call.

        The audit repo writes via ``session.add`` + ``session.flush``;
        watching ``db.add`` is the cheapest assertion that it ran.
        """

        async def _events(*_a: Any, **_kw: Any) -> AsyncGenerator[dict[str, Any], None]:
            yield _delta_event("ok")
            yield _chain_end_event("ok")

        mock_pipeline.astream_events = _events

        resp = client.post(
            "/chat/sandbox/stream",
            json={"source_id": str(SOURCE_ID), "query": "audit me"},
        )
        assert resp.status_code == 200
        # ``db.add`` is sync (SQLAlchemy contract) so it shows up on
        # the MagicMock as a call_count we can sample.
        assert db.add.call_count == 1


class TestSandboxRequestValidation:
    """Pydantic guards on the request shape — strict ``extra='forbid'``."""

    def test_unknown_field_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/chat/sandbox/stream",
            json={
                "source_id": str(SOURCE_ID),
                "query": "hi",
                "rogue": "field",
            },
        )
        assert resp.status_code == 422

    def test_history_capped_at_20(
        self,
        client: TestClient,
        mock_pipeline: AsyncMock,
    ) -> None:
        """30 turns submitted → only the last 20 are forwarded into state."""
        captured: dict[str, Any] = {}

        async def _events(
            state: Any, **_kw: Any
        ) -> AsyncGenerator[dict[str, Any], None]:
            captured["state"] = state
            yield _chain_end_event("ok")
            yield _delta_event("ok")

        mock_pipeline.astream_events = _events

        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn-{i}"}
            for i in range(30)
        ]
        resp = client.post(
            "/chat/sandbox/stream",
            json={
                "source_id": str(SOURCE_ID),
                "query": "next",
                "history": history,
            },
        )
        assert resp.status_code == 200
        # The last 20 turns make it into the seeded state.
        assert len(captured["state"]["messages"]) == 20
