"""Pydantic v2 schemas for chat sessions, messages, and streaming events."""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

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
    source_ids: list[str] | None = None


class ChatSessionUpdate(BaseModel):
    """Partial update for a chat session. At least one field is required.

    Title-only payloads come from the rename UI; source_ids-only payloads
    come from the source-picker on every selection change.  Both can be
    sent in a single PATCH if the caller wants to update both fields.
    """

    title: str | None = Field(default=None, max_length=255)
    source_ids: list[str] | None = None

    @field_validator("title")
    @classmethod
    def strip_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        return stripped

    @model_validator(mode="after")
    def at_least_one_field(self) -> ChatSessionUpdate:
        if self.title is None and self.source_ids is None:
            raise ValueError("at least one of {title, source_ids} must be provided")
        return self


class ChatSessionResponse(BaseModel):
    id: UUID
    # Nullable since U15 (lazy chat creation): until the first user message
    # is sent and the titler runs, a session row may have no title yet.  The
    # frontend renders a preview of the first user message as the fallback
    # label in that window.
    title: str | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    source_ids: list[str] = Field(default_factory=list)

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
    # User feedback on assistant messages — null when no thumbs given.
    # Surfaces the FeedbackButtons' initialRating so re-loading the chat
    # restores the user's prior up/down + comment.
    feedback_rating: int | None = None
    feedback_comment: str | None = None
    # NOTE: do NOT add a `metadata` field here.  The ChatMessage ORM has no
    # `metadata` column, and pydantic's from_attributes lookup would fall back
    # to SQLAlchemy's class-level `Base.metadata` (a MetaData() instance,
    # NOT a dict), causing model_validate() to crash with
    # `Input should be a valid dictionary [type=dict_type, input_value=MetaData()]`.
    # That bug 500'd GET /chat/sessions/{id} for any session with messages and
    # in turn broke the chat UI (see the MetaData-collision incident).  Use
    # `sources_cited`, `message_type`, or `is_partial` directly if you need
    # per-message side data.

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Chat request / response schemas
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4096)
    session_id: UUID | None = None
    stream: bool = False
    source_ids: list[str] | None = None

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
    TITLE = "title"
    # Emitted as the FIRST frame on the lazy-creation path
    # (``POST /sessions/new/messages``) so the client can swap the URL from
    # ``/chat`` → ``/chat/<id>`` and patch the sidebar cache before any
    # tokens flow.  Never emitted when the path already targets a real id.
    SESSION_CREATED = "session_created"
    # Agentic-pipeline events (T-052 owns these enum entries; T-053/T-056/T-057 emit them).
    PLAN = "plan"      # planner emits the step-by-step plan before execution
    STEP = "step"      # executor emits per-step progress events
    REPLAN = "replan"  # replan node emits a revised plan
    BUDGET = "budget"  # budget guard emits a cost-ceiling diagnostic


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
        # Compact agentic activity summary (T-058 / FR-018, FR-021). None for
        # non-agentic (v2 / legacy) turns — the activity UI hides what is
        # absent. Built by ``src.agent.activity_summary.build_activity_summary``
        # and persisted to ``chat_messages.activity_summary``.
        activity_summary: dict[str, Any] | None = None

    class ClarificationData(BaseModel):
        question: str

    class ErrorData(BaseModel):
        message: str
        code: str = "internal_error"

    class TitleData(BaseModel):
        title: str

    class SessionCreatedData(BaseModel):
        session_id: str
        source_ids: list[str] = Field(default_factory=list)

    def to_sse(self) -> str:
        """Format as a Server-Sent Event string.

        Emits proper SSE-spec frames — ``event: <name>\\ndata: <inner_json>\\n\\n`` —
        because the frontend's parseSseFrame() reads the event name from the
        ``event:`` header line, not from the JSON body.  Previously this method
        wrote the whole envelope (``data: {"event":..., "data":...}``) on a single
        ``data:`` line, leaving frame.event = the SSE default 'message' on the
        client and the entire switch falling through to the no-op default branch
        — i.e. tokens never rendered, ``done`` never invalidated the message
        cache. This was the second root cause of "I sent a message and got
        nothing back".
        """
        import json

        return f"event: {self.event.value}\ndata: {json.dumps(self.data)}\n\n"

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
        activity_summary: dict[str, Any] | None = None,
    ) -> ChatStreamEvent:
        return cls(
            event=StreamEventType.DONE,
            data={
                "session_id": session_id,
                "message_id": message_id,
                "trace_id": trace_id,
                "sources": sources or [],
                # Only included when the turn was agentic; None on v2/legacy so
                # the wire frame degrades gracefully (frontend hides what is absent).
                "activity_summary": activity_summary,
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

    @classmethod
    def title(cls, title: str) -> ChatStreamEvent:
        """Emit the auto-generated session title as the first SSE frame."""
        return cls(event=StreamEventType.TITLE, data={"title": title})

    @classmethod
    def session_created(
        cls,
        *,
        session_id: str,
        source_ids: list[str] | None = None,
    ) -> ChatStreamEvent:
        """Emit the freshly-created session id as the very first SSE frame.

        Used by the lazy-creation path (``POST /sessions/new/messages``) so
        the client can swap the URL to ``/chat/<id>`` and patch the sidebar
        cache before tokens start flowing.
        """
        return cls(
            event=StreamEventType.SESSION_CREATED,
            data={
                "session_id": session_id,
                "source_ids": source_ids or [],
            },
        )

    @classmethod
    def plan(
        cls,
        *,
        revision: int,
        reason: str | None,
        steps: list[dict[str, Any]],
    ) -> ChatStreamEvent:
        """Emit the planner's step-by-step plan before execution begins."""
        return cls(
            event=StreamEventType.PLAN,
            data={"revision": revision, "reason": reason, "steps": steps},
        )

    @classmethod
    def step(
        cls,
        *,
        step_id: str,
        role: str,
        state: str,
        label: str,
        summary: str | None = None,
        progress: dict[str, int] | None = None,
    ) -> ChatStreamEvent:
        """Emit progress for a single step (contracts/sse-events.md `step`).

        Shape matches what ``executor._step_event`` writes and the emitter sends
        verbatim: ``{step_id, role, state, label, summary, progress}``.
        """
        return cls(
            event=StreamEventType.STEP,
            data={
                "step_id": step_id,
                "role": role,
                "state": state,
                "label": label,
                "summary": summary,
                "progress": progress or {"current": 0, "total": 0},
            },
        )

    @classmethod
    def replan(
        cls,
        *,
        reason: str,
        superseded_revision: int,
    ) -> ChatStreamEvent:
        """Emit a replan notice (contracts/sse-events.md `replan`).

        Always followed by a fresh ``plan`` event with ``revision: 1``; the
        revised steps ride on that ``plan`` event, not here.
        """
        return cls(
            event=StreamEventType.REPLAN,
            data={"reason": reason, "superseded_revision": superseded_revision},
        )

    @classmethod
    def budget(
        cls,
        *,
        ceiling_hit: bool,
        not_completed: list[str],
        offer_continue: bool,
    ) -> ChatStreamEvent:
        """Emit a budget-ceiling notice (contracts/sse-events.md `budget`).

        Shape matches ``budget_guard``'s ``budget_event_data`` sent verbatim:
        ``{ceiling_hit, not_completed, offer_continue}``.
        """
        return cls(
            event=StreamEventType.BUDGET,
            data={
                "ceiling_hit": ceiling_hit,
                "not_completed": not_completed,
                "offer_continue": offer_continue,
            },
        )
