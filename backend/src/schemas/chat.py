"""Pydantic v2 schemas for chat sessions, messages, and streaming events."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MessageRoleSchema(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# Chat session schemas
# ---------------------------------------------------------------------------


class ChatSessionCreate(BaseModel):
    title: str = Field(default="New Chat", max_length=255)


class ChatSessionResponse(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ChatSessionListResponse(BaseModel):
    sessions: list[ChatSessionResponse]
    total: int


# ---------------------------------------------------------------------------
# Chat message schema
# ---------------------------------------------------------------------------


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: MessageRoleSchema
    content: str
    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Chat request / response schemas
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    session_id: UUID | None = None
    stream: bool = False

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        return v.strip()


class ChatResponse(BaseModel):
    answer: str
    session_id: UUID
    message_id: UUID
    trace_id: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Streaming event schemas
# ---------------------------------------------------------------------------


class StreamEventType(StrEnum):
    DELTA = "delta"
    DONE = "done"
    CLARIFICATION = "clarification"
    ERROR = "error"


class ChatStreamEvent(BaseModel):
    """A single server-sent event payload for chat streaming."""

    event: StreamEventType
    data: dict[str, Any] = Field(default_factory=dict)

    class DeltaData(BaseModel):
        token: str

    class DoneData(BaseModel):
        session_id: str
        message_id: str
        trace_id: str | None = None
        sources: list[dict[str, Any]] = Field(default_factory=list)

    class ClarificationData(BaseModel):
        question: str

    class ErrorData(BaseModel):
        message: str
        code: str = "internal_error"

    def to_sse(self) -> str:
        """Format as a Server-Sent Event string."""
        return f"data: {self.model_dump_json()}\n\n"

    @classmethod
    def delta(cls, token: str) -> ChatStreamEvent:
        return cls(event=StreamEventType.DELTA, data={"token": token})

    @classmethod
    def done(
        cls,
        *,
        session_id: str,
        message_id: str,
        trace_id: str | None = None,
        sources: list[dict[str, Any]] | None = None,
    ) -> ChatStreamEvent:
        return cls(
            event=StreamEventType.DONE,
            data={
                "session_id": session_id,
                "message_id": message_id,
                "trace_id": trace_id,
                "sources": sources or [],
            },
        )

    @classmethod
    def clarification(cls, question: str) -> ChatStreamEvent:
        return cls(
            event=StreamEventType.CLARIFICATION,
            data={"question": question},
        )

    @classmethod
    def error(cls, message: str, code: str = "internal_error") -> ChatStreamEvent:
        return cls(
            event=StreamEventType.ERROR,
            data={"message": message, "code": code},
        )
