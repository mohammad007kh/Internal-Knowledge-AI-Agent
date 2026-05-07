"""Unit tests for the chat sessions router — T-076."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-at-least-32-chars-long!!")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "test-jwt-refresh-secret-key-32-chars!!")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "testaccess")
os.environ.setdefault("MINIO_SECRET_KEY", "testsecret")
os.environ.setdefault("ENCRYPTION_KEY", "dGVzdGVuY3J5cHRpb25rZXkxMjM0NTY3ODk=")

from collections.abc import AsyncGenerator, AsyncIterator, Generator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from typing import Never  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.middleware.error_handler import register_exception_handlers  # noqa: E402
from src.api.v1.chat import (  # noqa: E402
    _get_chat_message_repo,
    _get_chat_session_repo,
    _get_chat_session_service,
    _get_db_session_factory,
    _get_pipeline,
    _get_title_generator,
    _get_tracing,
    router,
)
from src.core.deps import get_current_user  # noqa: E402
from src.models.chat import MessageRole  # noqa: E402
from src.models.user import User, UserRole  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
MESSAGE_ID = uuid.UUID("00000000-0000-0000-0000-000000000020")
TRACE_ID = "trace-abc-123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    user_id: uuid.UUID = USER_ID,
    email: str = "user@example.com",
    role: UserRole = UserRole.user,
) -> User:
    u = MagicMock(spec=User)
    u.id = user_id
    u.email = email
    u.role = role
    u.is_active = True
    return u


def _make_session(
    session_id: uuid.UUID = SESSION_ID,
    user_id: uuid.UUID = USER_ID,
    title: str = "Test session",
) -> MagicMock:
    _now = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    s = MagicMock()
    s.id = session_id
    s.user_id = user_id
    s.title = title
    s.created_at = _now
    s.updated_at = _now
    s.message_count = 0
    return s


def _make_message(
    message_id: uuid.UUID = MESSAGE_ID,
    session_id: uuid.UUID = SESSION_ID,
    role: MessageRole = MessageRole.USER,
    content: str = "Hello",
) -> MagicMock:
    m = MagicMock()
    m.id = message_id
    m.chat_session_id = session_id
    m.role = role
    m.content = content
    return m


def _make_db_context_manager(db_mock: AsyncMock) -> MagicMock:
    """Return a factory whose __call__ yields an async context manager."""

    @asynccontextmanager
    async def _ctx() -> AsyncIterator[AsyncMock]:
        yield db_mock

    factory = MagicMock()
    factory.return_value = _ctx()
    # Make every call return a fresh context manager
    factory.side_effect = lambda: _ctx()
    return factory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def current_user() -> User:
    return _make_user()


@pytest.fixture()
def db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def mock_session_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def mock_message_repo() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def mock_pipeline() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def mock_tracing() -> MagicMock:
    t = MagicMock()
    t.start_trace.return_value = TRACE_ID
    return t


@pytest.fixture()
def mock_chat_session_service() -> AsyncMock:
    svc = AsyncMock()
    svc.create_session.return_value = _make_session()
    svc.get_source_ids_for_session.return_value = []
    svc.get_owned_session.return_value = _make_session()
    return svc


@pytest.fixture()
def mock_title_generator() -> AsyncMock:
    """Default: returns None so existing tests are unaffected by the titler hook."""
    svc = AsyncMock()
    svc.generate_title = AsyncMock(return_value=None)
    return svc


@pytest.fixture()
def client(
    current_user: User,
    db: AsyncMock,
    mock_session_repo: AsyncMock,
    mock_message_repo: AsyncMock,
    mock_pipeline: AsyncMock,
    mock_tracing: MagicMock,
    mock_chat_session_service: AsyncMock,
    mock_title_generator: AsyncMock,
) -> Generator[TestClient, None, None]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/chat")

    db_factory = _make_db_context_manager(db)

    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[_get_db_session_factory] = lambda: db_factory
    app.dependency_overrides[_get_chat_session_repo] = lambda: mock_session_repo
    app.dependency_overrides[_get_chat_message_repo] = lambda: mock_message_repo
    app.dependency_overrides[_get_pipeline] = lambda: mock_pipeline
    app.dependency_overrides[_get_tracing] = lambda: mock_tracing
    app.dependency_overrides[_get_chat_session_service] = lambda: mock_chat_session_service
    app.dependency_overrides[_get_title_generator] = lambda: mock_title_generator

    with TestClient(app, raise_server_exceptions=False) as tc:
        yield tc


# ---------------------------------------------------------------------------
# POST /chat/sessions
# ---------------------------------------------------------------------------


class TestCreateSession:
    """POST /chat/sessions — create a new chat session."""

    def test_create_session_201(
        self,
        client: TestClient,
        mock_chat_session_service: AsyncMock,
    ) -> None:
        resp = client.post("/chat/sessions", json={"title": "Test session"})

        assert resp.status_code == 201
        mock_chat_session_service.create_session.assert_awaited_once()

    def test_create_session_calls_repo_with_user_id(
        self,
        client: TestClient,
        mock_chat_session_service: AsyncMock,
    ) -> None:
        client.post("/chat/sessions", json={"title": "My chat"})

        call_kwargs = mock_chat_session_service.create_session.call_args
        assert call_kwargs.kwargs.get("user_id") == str(USER_ID)
        assert call_kwargs.kwargs.get("title") == "My chat"


# ---------------------------------------------------------------------------
# GET /chat/sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    """GET /chat/sessions — list sessions for current user."""

    def test_list_sessions_200(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
    ) -> None:
        session_obj = _make_session()
        mock_session_repo.list_for_user.return_value = [session_obj]

        resp = client.get("/chat/sessions")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["sessions"]) == 1

    def test_list_sessions_empty(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
    ) -> None:
        mock_session_repo.list_for_user.return_value = []

        resp = client.get("/chat/sessions")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["sessions"] == []

    def test_list_sessions_calls_repo_with_user_id(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
    ) -> None:
        mock_session_repo.list_for_user.return_value = []

        client.get("/chat/sessions")

        mock_session_repo.list_for_user.assert_awaited_once_with(
            mock_session_repo.list_for_user.call_args.args[0],
            USER_ID,
        )


# ---------------------------------------------------------------------------
# GET /chat/sessions/{session_id}
# ---------------------------------------------------------------------------


class TestGetSession:
    """GET /chat/sessions/{session_id} — retrieve session + messages."""

    def test_get_session_200(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
    ) -> None:
        session_obj = _make_session()
        mock_session_repo.get.return_value = session_obj
        mock_message_repo.list_for_session.return_value = []

        with patch("src.api.v1.chat.ChatSessionResponse") as mock_resp, \
             patch("src.api.v1.chat.ChatMessageResponse"):
            mock_resp.model_validate.return_value = MagicMock(
                model_dump=lambda: {"id": str(SESSION_ID), "title": "Test"}
            )
            resp = client.get(f"/chat/sessions/{SESSION_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert "session" in body
        assert "messages" in body
        assert body["messages"] == []

    def test_get_session_403_wrong_owner(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
    ) -> None:
        # Session belongs to a different user
        session_obj = _make_session(user_id=OTHER_USER_ID)
        mock_session_repo.get.return_value = session_obj

        resp = client.get(f"/chat/sessions/{SESSION_ID}")

        assert resp.status_code == 403

    def test_get_session_403_not_found(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
    ) -> None:
        mock_session_repo.get.return_value = None

        resp = client.get(f"/chat/sessions/{SESSION_ID}")

        assert resp.status_code == 403

    def test_get_session_last_50_messages(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
    ) -> None:
        session_obj = _make_session()
        mock_session_repo.get.return_value = session_obj

        # 60 messages — endpoint should only return last 50
        messages = [
            _make_message(
                message_id=uuid.UUID(f"00000000-0000-0000-0000-{i:012d}"),
                content=f"msg {i}",
            )
            for i in range(1, 61)
        ]
        mock_message_repo.list_for_session.return_value = messages

        with patch("src.api.v1.chat.ChatSessionResponse") as mock_resp, \
             patch("src.api.v1.chat.ChatMessageResponse") as mock_msg_resp:
            mock_resp.model_validate.return_value = MagicMock(
                model_dump=lambda: {"id": str(SESSION_ID), "title": "Test"}
            )
            mock_msg_resp.model_validate.side_effect = lambda m: MagicMock(
                model_dump=lambda: {"content": m.content}
            )
            resp = client.get(f"/chat/sessions/{SESSION_ID}")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["messages"]) == 50


# ---------------------------------------------------------------------------
# DELETE /chat/sessions/{session_id}
# ---------------------------------------------------------------------------


class TestDeleteSession:
    """DELETE /chat/sessions/{session_id} — soft-delete a session."""

    def test_delete_session_204(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
    ) -> None:
        session_obj = _make_session()
        mock_session_repo.get.return_value = session_obj
        mock_session_repo.soft_delete.return_value = None

        resp = client.delete(f"/chat/sessions/{SESSION_ID}")

        assert resp.status_code == 204
        mock_session_repo.soft_delete.assert_awaited_once()

    def test_delete_session_403_wrong_owner(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
    ) -> None:
        session_obj = _make_session(user_id=OTHER_USER_ID)
        mock_session_repo.get.return_value = session_obj

        resp = client.delete(f"/chat/sessions/{SESSION_ID}")

        assert resp.status_code == 403
        mock_session_repo.soft_delete.assert_not_awaited()

    def test_delete_session_403_not_found(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
    ) -> None:
        mock_session_repo.soft_delete.return_value = None
        mock_session_repo.get.return_value = None

        resp = client.delete(f"/chat/sessions/{SESSION_ID}")

        assert resp.status_code == 403
        mock_session_repo.soft_delete.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /chat/sessions/{session_id}/messages  (SSE streaming)
# ---------------------------------------------------------------------------


class TestSendMessage:
    """POST /chat/sessions/{session_id}/messages — SSE streaming."""

    def _make_stream_event(self, delta_text: str) -> dict[str, object]:
        """Build a minimal on_chat_model_stream event dict."""
        chunk = MagicMock()
        chunk.content = delta_text
        return {
            "event": "on_chat_model_stream",
            "data": {"chunk": chunk},
            "name": "ChatModel",
        }

    def _make_chain_end_event(self, final_answer: str) -> dict[str, object]:
        return {
            "event": "on_chain_end",
            "name": "LangGraph",
            "data": {"output": {"final_answer": final_answer}},
        }

    def test_send_message_streams_sse(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_tracing: MagicMock,
    ) -> None:
        session_obj = _make_session()
        mock_session_repo.get.return_value = session_obj

        user_msg = _make_message(role=MessageRole.USER, content="Hello")
        assistant_msg = _make_message(role=MessageRole.ASSISTANT, content="Hi there")
        mock_message_repo.create.side_effect = [user_msg, assistant_msg]

        async def _fake_events(  # noqa: ARG001
            state: object, *, config: object, version: object
        ) -> AsyncGenerator[dict[str, object], None]:
            yield self._make_stream_event("Hi")
            yield self._make_stream_event(" there")
            yield self._make_chain_end_event("Hi there")

        mock_pipeline.astream_events = _fake_events

        resp = client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "Hello"},
        )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = resp.text
        # Should contain delta events
        assert "delta" in body
        # Should end with done event
        assert "done" in body

    def test_send_message_403_wrong_owner(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
    ) -> None:
        session_obj = _make_session(user_id=OTHER_USER_ID)
        mock_session_repo.get.return_value = session_obj

        resp = client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "Hello"},
        )

        assert resp.status_code == 403

    def test_send_message_403_session_not_found(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
    ) -> None:
        mock_session_repo.get.return_value = None

        resp = client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "Hello"},
        )

        assert resp.status_code == 403

    def test_send_message_pipeline_error_emits_error_event(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_tracing: MagicMock,
    ) -> None:
        session_obj = _make_session()
        mock_session_repo.get.return_value = session_obj

        user_msg = _make_message(role=MessageRole.USER, content="Explode")
        mock_message_repo.create.return_value = user_msg

        async def _failing_events(  # noqa: ARG001
            state: object, *, config: object, version: object
        ) -> AsyncGenerator[Never, None]:
            raise RuntimeError("Pipeline exploded")
            # yield needed to make this an async generator
            yield

        mock_pipeline.astream_events = _failing_events

        resp = client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "Explode"},
        )

        assert resp.status_code == 200
        assert "error" in resp.text

    def test_send_message_saves_user_message(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_tracing: MagicMock,
    ) -> None:
        """User message must be persisted before streaming starts."""
        session_obj = _make_session()
        mock_session_repo.get.return_value = session_obj

        user_msg = _make_message(role=MessageRole.USER, content="Persist me")
        assistant_msg = _make_message(role=MessageRole.ASSISTANT, content="OK")
        mock_message_repo.create.side_effect = [user_msg, assistant_msg]

        async def _empty_events(  # noqa: ARG001
            state: object, *, config: object, version: object
        ) -> AsyncGenerator[Never, None]:
            return
            yield

        mock_pipeline.astream_events = _empty_events

        client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "Persist me"},
        )

        first_create_call = mock_message_repo.create.call_args_list[0]
        assert first_create_call.kwargs.get("role") == MessageRole.USER
        assert first_create_call.kwargs.get("content") == "Persist me"

    def test_send_message_starts_langfuse_trace(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_tracing: MagicMock,
    ) -> None:
        session_obj = _make_session()
        mock_session_repo.get.return_value = session_obj

        user_msg = _make_message(role=MessageRole.USER, content="Trace me")
        assistant_msg = _make_message(role=MessageRole.ASSISTANT, content="Done")
        mock_message_repo.create.side_effect = [user_msg, assistant_msg]

        async def _empty_events(  # noqa: ARG001
            state: object, *, config: object, version: object
        ) -> AsyncGenerator[Never, None]:
            return
            yield

        mock_pipeline.astream_events = _empty_events

        client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "Trace me"},
        )

        mock_tracing.start_trace.assert_called_once_with(
            session_id=str(SESSION_ID),
            user_id=str(USER_ID),
            query="Trace me",
        )

    def test_send_message_empty_final_answer_skips_persist_and_emits_error(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_tracing: MagicMock,
    ) -> None:
        """Pipeline ending with empty final_answer must NOT INSERT a NULL row.

        Reproduces the bug where ``content`` (NOT NULL) crashes with
        ``NotNullViolationError`` and the SSE stream closes without a
        terminal frame, locking the frontend textarea.
        """
        session_obj = _make_session()
        mock_session_repo.get.return_value = session_obj

        user_msg = _make_message(role=MessageRole.USER, content="Hello")
        # Single side-effect — the assistant persist must NOT be called.
        mock_message_repo.create.side_effect = [user_msg]

        async def _empty_events(  # noqa: ARG001
            state: object, *, config: object, version: object
        ) -> AsyncGenerator[Never, None]:
            return
            yield

        mock_pipeline.astream_events = _empty_events

        resp = client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "Hello"},
        )

        assert resp.status_code == 200
        # Exactly one create call — the user message.  No assistant persist.
        assert mock_message_repo.create.await_count == 1
        first_call = mock_message_repo.create.call_args_list[0]
        assert first_call.kwargs.get("role") == MessageRole.USER

        # SSE body must contain a terminal error frame, not a done frame.
        body = resp.text
        assert "error" in body
        assert "empty_response" in body
        assert "\"event\":\"done\"" not in body

        # Trace must still be ended so Langfuse doesn't leak open spans.
        mock_tracing.end_trace.assert_called_once()

    def test_send_message_sse_headers(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_tracing: MagicMock,
    ) -> None:
        session_obj = _make_session()
        mock_session_repo.get.return_value = session_obj

        user_msg = _make_message(role=MessageRole.USER, content="Headers?")
        assistant_msg = _make_message(role=MessageRole.ASSISTANT, content="Yes")
        mock_message_repo.create.side_effect = [user_msg, assistant_msg]

        async def _empty_events(  # noqa: ARG001
            state: object, *, config: object, version: object
        ) -> AsyncGenerator[Never, None]:
            return
            yield

        mock_pipeline.astream_events = _empty_events

        resp = client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "Headers?"},
        )

        assert resp.headers.get("cache-control") == "no-cache"
        assert resp.headers.get("x-accel-buffering") == "no"


# ---------------------------------------------------------------------------
# Auto-titling — gates and SSE wiring
# ---------------------------------------------------------------------------


class TestAutoTitling:
    """POST /chat/sessions/{id}/messages — first-turn auto-title behaviour."""

    @staticmethod
    def _empty_pipeline_events() -> "Any":
        async def _events(  # noqa: ARG001
            state: object, *, config: object, version: object
        ) -> AsyncGenerator[Never, None]:
            return
            yield
        return _events

    def test_auto_titles_when_session_title_is_new_chat(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_title_generator: AsyncMock,
    ) -> None:
        """When session.title == 'New chat' and titler returns a string,
        the session is renamed AND the first SSE frame is event: title."""
        session_obj = _make_session(title="New chat")
        mock_session_repo.get.return_value = session_obj

        user_msg = _make_message(role=MessageRole.USER, content="Tell me about Q3")
        assistant_msg = _make_message(role=MessageRole.ASSISTANT, content="OK")
        mock_message_repo.create.side_effect = [user_msg, assistant_msg]

        mock_title_generator.generate_title = AsyncMock(return_value="Q3 EMEA growth")
        mock_pipeline.astream_events = self._empty_pipeline_events()

        resp = client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "Tell me about Q3"},
        )

        assert resp.status_code == 200
        # Titler was actually invoked
        mock_title_generator.generate_title.assert_awaited_once_with("Tell me about Q3")
        # Session was renamed in the request-scoped DB session
        mock_session_repo.rename.assert_awaited_once()
        rename_args = mock_session_repo.rename.call_args
        assert rename_args.args[1] == SESSION_ID
        assert rename_args.args[2] == "Q3 EMEA growth"
        # SSE body's first data frame carries the title event
        body = resp.text
        assert '"event":"title"' in body
        assert '"title":"Q3 EMEA growth"' in body
        # Title frame must precede the done frame in the stream
        assert body.index('"event":"title"') < body.index('"event":"done"')

    def test_no_titler_call_when_title_already_set(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_title_generator: AsyncMock,
    ) -> None:
        """User-renamed sessions must skip the titler entirely."""
        session_obj = _make_session(title="My custom title")
        mock_session_repo.get.return_value = session_obj

        user_msg = _make_message(role=MessageRole.USER, content="hi")
        assistant_msg = _make_message(role=MessageRole.ASSISTANT, content="hello")
        mock_message_repo.create.side_effect = [user_msg, assistant_msg]
        mock_pipeline.astream_events = self._empty_pipeline_events()

        resp = client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "hi"},
        )

        assert resp.status_code == 200
        mock_title_generator.generate_title.assert_not_awaited()
        mock_session_repo.rename.assert_not_awaited()
        assert '"event":"title"' not in resp.text

    def test_no_title_event_when_titler_returns_none(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_title_generator: AsyncMock,
    ) -> None:
        """Timeout / refusal / empty: silent fallback — no rename, no SSE frame."""
        session_obj = _make_session(title="New chat")
        mock_session_repo.get.return_value = session_obj

        user_msg = _make_message(role=MessageRole.USER, content="hi")
        assistant_msg = _make_message(role=MessageRole.ASSISTANT, content="hello")
        mock_message_repo.create.side_effect = [user_msg, assistant_msg]

        mock_title_generator.generate_title = AsyncMock(return_value=None)
        mock_pipeline.astream_events = self._empty_pipeline_events()

        resp = client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "hi"},
        )

        assert resp.status_code == 200
        mock_title_generator.generate_title.assert_awaited_once()
        mock_session_repo.rename.assert_not_awaited()
        assert '"event":"title"' not in resp.text

    def test_titler_exception_falls_back_silently(
        self,
        client: TestClient,
        mock_session_repo: AsyncMock,
        mock_message_repo: AsyncMock,
        mock_pipeline: AsyncMock,
        mock_title_generator: AsyncMock,
    ) -> None:
        """If the titler itself raises, the chat path must continue uninterrupted."""
        session_obj = _make_session(title="New chat")
        mock_session_repo.get.return_value = session_obj

        user_msg = _make_message(role=MessageRole.USER, content="hi")
        assistant_msg = _make_message(role=MessageRole.ASSISTANT, content="hello")
        mock_message_repo.create.side_effect = [user_msg, assistant_msg]

        mock_title_generator.generate_title = AsyncMock(
            side_effect=RuntimeError("titler exploded")
        )
        mock_pipeline.astream_events = self._empty_pipeline_events()

        resp = client.post(
            f"/chat/sessions/{SESSION_ID}/messages",
            json={"query": "hi"},
        )

        assert resp.status_code == 200
        mock_session_repo.rename.assert_not_awaited()
        assert '"event":"title"' not in resp.text
        # done event still fires — chat is never broken by the titler
        assert '"event":"done"' in resp.text
