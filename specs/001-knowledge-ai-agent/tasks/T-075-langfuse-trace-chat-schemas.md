# T-075 â€” Langfuse Trace Lifecycle + Pydantic Chat Schemas

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· Pydantic v2 Â· dependency-injector
LangGraph 8-node Â· SSE streaming
Langfuse self-hosted â€” traces include: session_id, user_id, query, node spans, tokens
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
```

## Goal
1. Implement `LangfuseTracingService` â€” creates a trace per pipeline run,
   flushes on completion, and exposes a trace URL for debugging  
2. Define all Pydantic v2 request/response schemas used by the Chat API  
3. Register `LangfuseTracingService` in the DI container

---

## Acceptance Criteria

- [ ] `LangfuseTracingService.start_trace()` returns a `trace_id` string
- [ ] `LangfuseTracingService.end_trace()` calls `langfuse.flush()`
- [ ] `ChatSessionCreate`, `ChatSessionResponse`, `ChatMessageResponse`, `ChatRequest`, `ChatStreamEvent` schemas importable from `app.schemas.chat`
- [ ] `ChatStreamEvent` serialises cleanly to JSON for SSE
- [ ] `ChatSessionResponse` includes `id`, `title`, `created_at`, `message_count`
- [ ] Container registers `langfuse_tracing_service`

---

## 1  `app/services/langfuse_tracing_service.py`

```python
# app/services/langfuse_tracing_service.py
"""Per-run Langfuse trace lifecycle management."""
from __future__ import annotations

import logging
from uuid import uuid4

from langfuse import Langfuse

logger = logging.getLogger(__name__)


class LangfuseTracingService:
    """Wraps Langfuse to create and finalise traces for LangGraph runs.

    One instance per application lifetime (singleton DI scope).
    Traces are keyed by ``trace_id`` (UUID), which is stored in
    ``AgentState["trace_id"]`` so every node can emit spans against it.
    """

    def __init__(self, langfuse: Langfuse) -> None:
        self._lf = langfuse

    # â”€â”€ Lifecycle â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def start_trace(
        self,
        *,
        session_id: str,
        user_id: str,
        query: str,
    ) -> str:
        """Create a new Langfuse trace and return its ``trace_id``.

        The returned ID must be passed into ``AgentState["trace_id"]`` so
        that all node spans are attached to the same trace.
        """
        trace_id = str(uuid4())
        self._lf.trace(
            id=trace_id,
            name="chat_pipeline",
            user_id=user_id,
            session_id=session_id,
            input={"query": query[:500]},
            metadata={"session_id": session_id},
        )
        logger.debug("langfuse trace started trace_id=%s session=%s", trace_id, session_id)
        return trace_id

    def end_trace(self, trace_id: str, *, output: str, error: str | None = None) -> None:
        """Update the trace with the final output and flush."""
        self._lf.trace(
            id=trace_id,
            output={"answer": output[:1000], "error": error},
        )
        self._lf.flush()
        logger.debug("langfuse trace ended trace_id=%s", trace_id)

    def trace_url(self, trace_id: str) -> str | None:
        """Return the Langfuse UI URL for this trace (debugging only)."""
        try:
            return f"{self._lf.base_url}/trace/{trace_id}"
        except AttributeError:
            return None
```

---

## 2  `app/schemas/chat.py`

```python
# app/schemas/chat.py
"""Pydantic v2 schemas for chat sessions and messages."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# â”€â”€ Enums â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class MessageRoleSchema(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# â”€â”€ Chat Session â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ChatSessionCreate(BaseModel):
    """Request body to create a new chat session."""

    title: str = Field(
        default="New conversation",
        min_length=1,
        max_length=200,
    )
    source_ids: list[str] = Field(
        default_factory=list,
        description="Pre-selected source UUIDs for this conversation.",
    )


class ChatSessionResponse(BaseModel):
    """API response for a chat session."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = Field(default=0)

    model_config = {"from_attributes": True}


class ChatSessionListResponse(BaseModel):
    """Paginated list of chat sessions."""

    items: list[ChatSessionResponse]
    total: int
    limit: int
    offset: int


# â”€â”€ Chat Messages â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ChatMessageResponse(BaseModel):
    """API response for a single chat message."""

    id: str
    session_id: str
    role: MessageRoleSchema
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


# â”€â”€ Chat Request / Response (non-streaming) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class ChatRequest(BaseModel):
    """Body for POST /chat/sessions/{session_id}/messages."""

    query: str = Field(
        min_length=1,
        max_length=4096,
        description="The user's question or message.",
    )
    source_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Override which sources are searched.  If empty, uses all sources "
            "the user has access to."
        ),
    )

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        return v.strip()


class ChatResponse(BaseModel):
    """Non-streaming chat response."""

    session_id: str
    message: ChatMessageResponse
    trace_id: str
    requires_clarification: bool = False
    clarification_question: Optional[str] = None


# â”€â”€ SSE Streaming Events â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class StreamEventType(str, Enum):
    DELTA = "delta"            # Partial text token
    DONE = "done"              # Final answer complete
    CLARIFICATION = "clarification"  # interrupt() triggered
    ERROR = "error"            # Pipeline error


class ChatStreamEvent(BaseModel):
    """A single SSE payload sent to the client.

    Serialised as: ``data: <json>\\n\\n``
    """

    event: StreamEventType
    data: Any = None

    class DeltaData(BaseModel):
        token: str

    class DoneData(BaseModel):
        session_id: str
        message_id: str
        trace_id: str

    class ClarificationData(BaseModel):
        question: str

    class ErrorData(BaseModel):
        code: str
        message: str

    def to_sse(self) -> str:
        """Format as a raw SSE string."""
        return f"data: {self.model_dump_json()}\n\n"
```

---

## 3  `app/schemas/__init__.py` â€” patch

```python
# Append:
from app.schemas.chat import (  # noqa: F401
    ChatMessageResponse,
    ChatRequest,
    ChatResponse,
    ChatSessionCreate,
    ChatSessionListResponse,
    ChatSessionResponse,
    ChatStreamEvent,
    StreamEventType,
)
```

---

## 4  `containers.py` â€” patch

```python
# Add after langfuse singleton:

from app.services.langfuse_tracing_service import LangfuseTracingService

langfuse_tracing_service = providers.Singleton(
    LangfuseTracingService,
    langfuse=langfuse,
)
```

---

## 5  Unit Tests â€” `tests/unit/services/test_langfuse_tracing_service.py`

```python
# tests/unit/services/test_langfuse_tracing_service.py
from unittest.mock import MagicMock

import pytest

from app.services.langfuse_tracing_service import LangfuseTracingService


@pytest.fixture()
def service():
    mock_lf = MagicMock()
    mock_lf.base_url = "https://langfuse.example.com"
    return LangfuseTracingService(langfuse=mock_lf), mock_lf


def test_start_trace_returns_uuid(service):
    svc, mock_lf = service
    tid = svc.start_trace(session_id="s1", user_id="u1", query="test query")
    assert len(tid) == 36  # UUID4 string
    mock_lf.trace.assert_called_once()


def test_end_trace_flushes(service):
    svc, mock_lf = service
    svc.end_trace("trace-123", output="answer text")
    mock_lf.flush.assert_called_once()


def test_trace_url_contains_id(service):
    svc, _ = service
    url = svc.trace_url("abc-123")
    assert "abc-123" in url


def test_schema_sse_format():
    from app.schemas.chat import ChatStreamEvent, StreamEventType

    event = ChatStreamEvent(event=StreamEventType.DELTA, data={"token": "Hello"})
    sse = event.to_sse()
    assert sse.startswith("data: ")
    assert sse.endswith("\n\n")
    assert '"delta"' in sse
```

---

## Files Modified / Created

| Action | Path |
|---|---|
| CREATE | `app/services/langfuse_tracing_service.py` |
| CREATE | `app/schemas/chat.py` |
| PATCH  | `app/schemas/__init__.py` |
| PATCH  | `containers.py` |
| CREATE | `tests/unit/services/test_langfuse_tracing_service.py` |
