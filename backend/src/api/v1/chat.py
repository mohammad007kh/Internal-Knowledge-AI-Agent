"""Chat sessions API router — T-076."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import get_current_user, require_admin
from src.core.problem_details import problem
from src.models.chat import MessageRole
from src.models.user import User
from src.repositories.admin_audit_log_repository import AdminAuditLogRepository
from src.repositories.chat_repository import ChatMessageRepository, ChatSessionRepository
from src.schemas.chat import (
    ChatMessageResponse,
    ChatRequest,
    ChatSessionCreate,
    ChatSessionListResponse,
    ChatSessionResponse,
    ChatSessionUpdate,
    ChatStreamEvent,
)
from src.services.audit_service import emit_audit
from src.services.chat_stream_service import (
    SANDBOX_SESSION_ID,
    history_to_lc_messages,
    run_pipeline_stream,
)
from src.services.langfuse_tracing_service import LangfuseTracingService

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# DI helper functions
# ---------------------------------------------------------------------------


def _get_db_session_factory() -> Any:
    from src.core.container import Container  # noqa: PLC0415

    return Container.session_factory_provider()


def _get_chat_session_repo() -> ChatSessionRepository:
    """Return a stateless ChatSessionRepository.

    The repo's methods accept the active :class:`AsyncSession` per call,
    so the constructor argument is unused and we no longer route through
    :class:`Container` (which would hand back a repo bound to a brand-new,
    non-request-scoped session — the connection-pool leak this slice fixes).
    """
    return ChatSessionRepository()


def _get_chat_message_repo() -> ChatMessageRepository:
    """Return a stateless ChatMessageRepository.  See :func:`_get_chat_session_repo`."""
    return ChatMessageRepository()


def _get_pipeline() -> Any:
    from src.core.container import Container  # noqa: PLC0415

    return Container.pipeline()


def _get_tracing() -> LangfuseTracingService:
    from src.core.container import Container  # noqa: PLC0415

    return Container.langfuse_tracing_service()


def _get_chat_session_service() -> Any:
    from src.core.container import Container  # noqa: PLC0415

    return Container.chat_session_service()


def _get_title_generator() -> Any:
    from src.core.container import Container  # noqa: PLC0415

    return Container.title_generator_service()


# ---------------------------------------------------------------------------
# Ownership guard
# ---------------------------------------------------------------------------


def _assert_session_owner(session_obj: Any, user: User) -> None:
    if session_obj is None or session_obj.user_id != user.id:
        raise problem(
            status=403,
            title="Forbidden",
            detail="You do not have access to this chat session.",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/sessions", status_code=status.HTTP_201_CREATED, response_model=ChatSessionResponse)
async def create_session(
    body: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    chat_session_service: Any = Depends(_get_chat_session_service),
) -> ChatSessionResponse:
    """Create a new chat session for the authenticated user."""
    session_obj = await chat_session_service.create_session(
        db,
        user_id=str(current_user.id),
        title=body.title,
        source_ids=body.source_ids,
    )
    await db.commit()
    return ChatSessionResponse.model_validate(session_obj)


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    chat_session_repo: ChatSessionRepository = Depends(_get_chat_session_repo),
) -> ChatSessionListResponse:
    """List all chat sessions for the authenticated user."""
    sessions = await chat_session_repo.list_for_user(db, current_user.id)
    session_responses = [ChatSessionResponse.model_validate(s) for s in sessions]
    return ChatSessionListResponse(sessions=session_responses, total=len(session_responses))


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    chat_session_repo: ChatSessionRepository = Depends(_get_chat_session_repo),
    chat_message_repo: ChatMessageRepository = Depends(_get_chat_message_repo),
) -> dict[str, Any]:
    """Retrieve a chat session with its last 50 messages."""
    session_obj = await chat_session_repo.get(db, session_id)
    _assert_session_owner(session_obj, current_user)

    messages = await chat_message_repo.list_for_session(db, chat_session_id=session_id)
    last_50 = messages[-50:]

    return {
        "session": ChatSessionResponse.model_validate(session_obj),
        "messages": [ChatMessageResponse.model_validate(m) for m in last_50],
    }


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
async def update_session(
    session_id: uuid.UUID,
    body: ChatSessionUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    chat_session_repo: ChatSessionRepository = Depends(_get_chat_session_repo),
) -> ChatSessionResponse:
    """Partial-update a chat session.  Body fields:

    - ``title``: new title (1-255 chars, stripped).  Used by rename UI.
    - ``source_ids``: replacement allowlist.  Used by the chat source-picker
      on every selection change.  Empty list means "no per-session filter —
      retrieve across every source the user can access".

    At least one field must be provided; if both are present, both are
    applied in the same transaction.  Pre-fix this endpoint was
    rename-only and silently 400'd source-picker writes, which left
    chat_sessions.source_ids stuck at [] forever and made retrieval fall
    back to the bot's "no information" boilerplate.
    """
    session_obj = await chat_session_repo.get(db, session_id)
    _assert_session_owner(session_obj, current_user)

    updated = session_obj
    if body.title is not None:
        updated = await chat_session_repo.rename(db, session_id, body.title) or updated
    if body.source_ids is not None:
        updated = (
            await chat_session_repo.update_source_ids(db, session_id, body.source_ids)
            or updated
        )
    await db.commit()
    return ChatSessionResponse.model_validate(updated)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    chat_session_repo: ChatSessionRepository = Depends(_get_chat_session_repo),
) -> Response:
    """Soft-delete a chat session belonging to the authenticated user."""
    session_obj = await chat_session_repo.get(db, session_id)
    _assert_session_owner(session_obj, current_user)

    await chat_session_repo.soft_delete(db, session_id)
    await db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    db_session_factory: Any = Depends(_get_db_session_factory),
    chat_session_repo: ChatSessionRepository = Depends(_get_chat_session_repo),
    chat_message_repo: ChatMessageRepository = Depends(_get_chat_message_repo),
    pipeline: Any = Depends(_get_pipeline),
    langfuse_tracing: LangfuseTracingService = Depends(_get_tracing),
    chat_session_service: Any = Depends(_get_chat_session_service),
    title_generator_service: Any = Depends(_get_title_generator),
) -> StreamingResponse:
    """Stream an AI response for a user query within a chat session."""

    # Verify ownership and resolve source_ids on the request-scoped session.
    session_obj = await chat_session_repo.get(db, session_id)
    _assert_session_owner(session_obj, current_user)
    source_ids = await chat_session_service.get_source_ids_for_session(
        db,
        session=session_obj,
        user_id=str(current_user.id),
        override_ids=body.source_ids,
    )

    # Decide BEFORE persisting whether this is the session's first user
    # turn — manual rename preservation hinges on the placeholder title
    # being intact at request entry.  We re-check before the LLM call so
    # a concurrent rename in another tab still wins the race.
    #
    # Accept all three default-title sentinels that exist across the create
    # paths in this codebase (lowercase 'New chat' from the frontend, capital
    # 'New Chat' from ChatSessionCreate's pydantic default, 'New conversation'
    # from the model + repo + service defaults).  Any of them indicates the
    # user has not yet chosen / been-given a real title, so titling is fair
    # game — but a manually-renamed title (anything else) is preserved.
    _PLACEHOLDER_TITLES = {"New chat", "New Chat", "New conversation"}
    should_title = session_obj.title in _PLACEHOLDER_TITLES

    # Persist the user message before the response stream begins so the
    # follow-up generator (which opens fresh sessions) sees a consistent state.
    await chat_message_repo.create(
        db,
        chat_session_id=session_id,
        role=MessageRole.USER,
        content=body.query,
    )
    await db.commit()

    # Auto-titler — synchronous, 2 s timeout, silent fallback on any failure.
    # Runs AFTER the user message is persisted so the chat record is durable
    # even if the title call hangs all the way to its deadline.
    generated_title: str | None = None
    if should_title:
        try:
            candidate = await title_generator_service.generate_title(body.query)
        except Exception:  # noqa: BLE001 — never block chat on titler errors
            logger.warning("send_message: title generation raised", exc_info=True)
            candidate = None
        if candidate:
            try:
                await chat_session_repo.rename(db, session_id, candidate)
                await db.commit()
                generated_title = candidate
            except Exception:  # noqa: BLE001 — silent fallback on rename failure
                logger.warning(
                    "send_message: persisting auto-title failed", exc_info=True
                )

    # Start Langfuse trace
    trace_id: str = langfuse_tracing.start_trace(
        session_id=str(session_id),
        user_id=str(current_user.id),
        query=body.query,
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        config: dict[str, Any] = {"configurable": {"thread_id": str(session_id)}}
        initial_state: dict[str, Any] = {
            # load_history populates messages from DB (the just-persisted user row
            # is included) so seeding here would double-insert and confuse the
            # history-aware analyzer.  Empty seed is correct.
            "messages": [],
            "retrieved_chunks": [],
            "requires_clarification": False,
            "clarification_question": None,
            "session_id": str(session_id),
            "user_id": str(current_user.id),
            "trace_id": trace_id,
            "query": body.query,
            "final_answer": None,
            "error": None,
            "source_ids": source_ids,
            "sources": [],
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        }

        # Emit the auto-generated title BEFORE the first pipeline event so
        # the frontend can repaint the sidebar entry while the LLM warms up.
        pre_yield: list[str] = []
        if generated_title:
            pre_yield.append(ChatStreamEvent.title(generated_title).to_sse())

        # Track the running answer so we can persist a partial on
        # GeneratorExit (client disconnect). The shared helper does its
        # own bookkeeping but doesn't expose mid-stream state — we
        # tee the deltas here so the partial-persist branch can recover.
        partial_answer = ""

        async def _persist_assistant(final_answer: str) -> str:
            """Persist the completed assistant turn and return its id.

            Runs inside the shared helper's success path. Errors propagate
            up — :func:`run_pipeline_stream` converts them into a
            ``persist_error`` SSE frame.
            """
            async with db_session_factory() as fresh_db:
                assistant_msg = await chat_message_repo.create(
                    fresh_db,
                    chat_session_id=session_id,
                    role=MessageRole.ASSISTANT,
                    content=final_answer,
                    is_partial=False,
                )
                await fresh_db.commit()
                return str(assistant_msg.id)

        try:
            async for frame in run_pipeline_stream(
                pipeline=pipeline,
                initial_state=initial_state,
                config=config,
                trace_id=trace_id,
                session_id=str(session_id),
                langfuse_tracing=langfuse_tracing,
                persist_assistant=True,
                on_done=_persist_assistant,
                pre_yield=pre_yield,
            ):
                # Tee delta tokens so we can recover the partial on disconnect.
                # The frame format is ``event: delta\ndata: {"token": "…"}\n\n``;
                # we only need the bookkeeping side, not parsing — the helper
                # already accumulated final_answer for its own success path.
                # Keeping a local mirror is the cheapest way to stay correct
                # under GeneratorExit (we lose the helper's locals at that
                # point).
                if "event: delta" in frame:
                    # Best-effort partial reconstruction; payload is JSON
                    # following the ``data: `` prefix on the second line.
                    try:
                        import json  # noqa: PLC0415

                        data_line = frame.split("\ndata: ", 1)[1].rstrip("\n")
                        partial_answer += json.loads(data_line).get("token", "")
                    except Exception:  # noqa: BLE001
                        # Tee is best-effort — never break the user-facing stream.
                        pass
                yield frame
        except GeneratorExit:
            # Client disconnected mid-stream. Persist whatever tokens we
            # already shipped to the wire so the session has a record;
            # skip when nothing real was emitted (``content`` is NOT NULL).
            if not partial_answer:
                logger.warning(
                    "Chat stream aborted with empty final_answer for session=%s — "
                    "skipping partial persist",
                    session_id,
                )
                try:
                    langfuse_tracing.end_trace(trace_id, output="[aborted]")
                except Exception:  # noqa: BLE001
                    logger.debug("end_trace failed after disconnect", exc_info=True)
                return
            async with db_session_factory() as fresh_db:
                try:
                    await chat_message_repo.create(
                        fresh_db,
                        chat_session_id=session_id,
                        role=MessageRole.ASSISTANT,
                        content=partial_answer,
                        is_partial=True,
                    )
                    await fresh_db.commit()
                except Exception:
                    logger.exception(
                        "Failed to persist partial message for session=%s", session_id
                    )
            try:
                langfuse_tracing.end_trace(trace_id, output="[aborted]")
            except Exception:  # noqa: BLE001
                logger.debug("end_trace failed after disconnect", exc_info=True)
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Sandbox streaming (admin-only) — Slice A
# ---------------------------------------------------------------------------
#
# The sandbox endpoint runs the full agent pipeline against ONE source so
# admins can debug retrieval failures (a broken DB connection, a stale
# embedder, a malformed schema document) without polluting chat_sessions /
# chat_messages with throwaway runs. It deliberately bypasses both
# ``is_active`` (admins specifically test broken sources) AND the
# permission-list filter (admin auth gates the endpoint already).
#
# The SSE event grammar is byte-identical to the session-chat endpoint so
# the frontend's :file:`use-chat-stream.ts` hook is reusable. The sandbox
# emits ``session_id="__sandbox__"`` and ``message_id=""`` in the ``done``
# event so client code can branch on the sentinel without parsing the URL.
#
# Rate limiting: the endpoint inherits the global rate-limit middleware —
# we deliberately do NOT bypass it. TODO(slice-A+1): if admins start
# triggering the global bucket while debugging, add a per-admin sandbox
# bucket with a tighter ceiling (e.g. 30 calls/min) so a runaway script
# can't starve real chat traffic.

from pydantic import BaseModel, ConfigDict, Field  # noqa: E402,PLC0415


class _SandboxHistoryTurn(BaseModel):
    """One turn of the sandbox conversation (OpenAI-style)."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., min_length=1, max_length=4096)


class _SandboxRequest(BaseModel):
    """Body for ``POST /chat/sandbox/stream``."""

    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID
    query: str = Field(..., min_length=1, max_length=4096)
    # Capped at 20 turns server-side. Clients SHOULD cap on their side too,
    # but defence-in-depth: the validator below truncates rather than
    # rejecting so a 21st turn doesn't eat a 422 in front of the user.
    history: list[_SandboxHistoryTurn] | None = None

    @classmethod
    def _max_history_turns(cls) -> int:
        return 20


@router.post(
    "/sandbox/stream",
    summary="Admin-only streaming chat against a single source (no persistence)",
    dependencies=[Depends(require_admin)],
)
async def sandbox_stream(
    body: _SandboxRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    pipeline: Any = Depends(_get_pipeline),
    langfuse_tracing: LangfuseTracingService = Depends(_get_tracing),
) -> StreamingResponse:
    """Run the agent pipeline against ONE source and stream SSE.

    Persists nothing to chat_sessions / chat_messages / message_feedback.
    Emits exactly one ``admin_audit_log`` row per call. The Langfuse trace
    IS recorded — the whole purpose of the endpoint is debugging — but is
    tagged with ``sandbox=True`` and the ``source_id`` so analytics can
    exclude these from production funnel metrics.

    Bypasses ``Source.is_active`` (admins specifically test rejected /
    pending sources) and the permission-list filter on chat picker
    (admin role-check at the endpoint level is the gate).
    """
    # 404 the source if it doesn't exist or is soft-deleted. Admins still
    # see is_active=False sources by design — that's the whole point of
    # the sandbox.
    from sqlalchemy import select  # noqa: PLC0415

    from src.models.source import Source  # noqa: PLC0415

    src = await db.scalar(
        select(Source).where(
            Source.id == body.source_id,
            Source.deleted_at.is_(None),
        )
    )
    if src is None:
        raise problem(
            status=404,
            title="Source not found",
            detail=f"No source found for id {body.source_id}.",
        )

    # Hard-cap history at 20 turns server-side (defence-in-depth — the
    # frontend should already cap, but a misconfigured client must not be
    # able to OOM the agent's context window).
    raw_history = body.history or []
    capped = raw_history[-_SandboxRequest._max_history_turns() :]
    lc_history = history_to_lc_messages(
        [{"role": h.role, "content": h.content} for h in capped]
    )

    # Start a Langfuse trace tagged for sandbox use. Re-using start_trace
    # keeps the wiring identical to production but the metadata makes
    # downstream filtering trivial.
    trace_id: str = langfuse_tracing.start_trace(
        session_id=SANDBOX_SESSION_ID,
        user_id=str(current_user.id),
        query=body.query,
    )

    # Single audit row per sandbox call. Capture only what helps an SRE
    # later: query length (NEVER the query text — sandbox prompts can
    # contain pasted PII while admins are debugging) and the trace id so
    # they can jump to the trace from the audit search UI.
    await emit_audit(
        AdminAuditLogRepository(db),
        admin_user_id=current_user.id,
        action="source.sandbox_query",
        resource_type="source",
        resource_id=body.source_id,
        request=request,
        metadata={"query_len": len(body.query), "trace_id": trace_id},
    )
    await db.commit()

    config: dict[str, Any] = {
        "configurable": {"thread_id": SANDBOX_SESSION_ID},
        # Langfuse v4 reads tags off the runtime config; production traces
        # don't carry these so dashboards can filter sandbox out.
        "metadata": {"sandbox": True, "source_id": str(body.source_id)},
        "tags": ["sandbox"],
    }
    initial_state: dict[str, Any] = {
        "messages": lc_history,
        "retrieved_chunks": [],
        "requires_clarification": False,
        "clarification_question": None,
        "session_id": SANDBOX_SESSION_ID,
        "user_id": str(current_user.id),
        "trace_id": trace_id,
        "query": body.query,
        "final_answer": None,
        "error": None,
        # Single source — bypass the permission filter by passing the id
        # straight in. The pipeline doesn't re-check permissions on this
        # field; admin auth at the endpoint is the gate.
        "source_ids": [str(body.source_id)],
        "sources": [],
        "total_input_tokens": 0,
        "total_output_tokens": 0,
    }

    async def _sandbox_event_generator() -> AsyncGenerator[str, None]:
        async for frame in run_pipeline_stream(
            pipeline=pipeline,
            initial_state=initial_state,
            config=config,
            trace_id=trace_id,
            session_id=SANDBOX_SESSION_ID,
            langfuse_tracing=langfuse_tracing,
            persist_assistant=False,  # sandbox never writes to chat_messages
            on_done=None,
        ):
            yield frame

    return StreamingResponse(
        _sandbox_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# Per-message feedback (thumbs up / thumbs down)
# ---------------------------------------------------------------------------


class _FeedbackRequest(BaseModel):
    """Body for ``POST /sessions/{session_id}/messages/{message_id}/feedback``."""

    model_config = ConfigDict(extra="forbid")

    rating: int = Field(..., description="+1 thumbs up, -1 thumbs down.")
    comment: str | None = Field(default=None, max_length=500)


class _FeedbackResponse(BaseModel):
    id: str
    rating: int
    comment: str | None


@router.post(
    "/sessions/{session_id}/messages/{message_id}/feedback",
    response_model=_FeedbackResponse,
    summary="Persist user feedback (thumbs up/down + optional comment) on a message",
)
async def submit_message_feedback(
    session_id: uuid.UUID,
    message_id: uuid.UUID,
    body: _FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> _FeedbackResponse:
    """Update the feedback rating + comment on a single chat message.

    The frontend's :file:`FeedbackButtons.tsx` renders the up/down buttons on
    every assistant bubble; before this endpoint existed the mutation
    silently 404'd in production. The endpoint is idempotent — reposting
    overrides the previous feedback.

    Authorization: the caller must own the chat session that the message
    belongs to. Admins can update feedback on any message.
    """
    if body.rating not in (-1, 1):
        return problem(
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Invalid rating",
            detail="rating must be either +1 (thumbs up) or -1 (thumbs down).",
        )

    from sqlalchemy import select  # noqa: PLC0415

    from src.models.chat import ChatMessage, ChatSession  # noqa: PLC0415

    msg = await db.scalar(
        select(ChatMessage).where(
            ChatMessage.id == message_id,
            ChatMessage.session_id == session_id,
        )
    )
    if msg is None:
        return problem(
            status=status.HTTP_404_NOT_FOUND,
            title="Message not found",
            detail="No message found for that session_id / message_id pair.",
        )

    # Ownership: load the parent session and confirm the caller owns it
    # (or is an admin).
    session = await db.scalar(
        select(ChatSession).where(ChatSession.id == session_id)
    )
    if session is None:
        return problem(
            status=status.HTTP_404_NOT_FOUND,
            title="Session not found",
            detail="No session found for that session_id.",
        )
    from src.models.user import UserRole  # noqa: PLC0415

    if (
        current_user.role != UserRole.admin
        and str(session.user_id) != str(current_user.id)
    ):
        return problem(
            status=status.HTTP_403_FORBIDDEN,
            title="Forbidden",
            detail="You may only submit feedback on messages from your own sessions.",
        )

    msg.feedback_rating = body.rating
    msg.feedback_comment = (body.comment or "").strip() or None
    await db.commit()

    return _FeedbackResponse(
        id=str(msg.id),
        rating=msg.feedback_rating,
        comment=msg.feedback_comment,
    )
