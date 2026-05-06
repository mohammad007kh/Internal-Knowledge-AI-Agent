"""Chat sessions API router — T-076."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import get_current_user
from src.core.problem_details import problem
from src.models.chat import MessageRole
from src.models.user import User
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

    # Persist the user message before the response stream begins so the
    # follow-up generator (which opens fresh sessions) sees a consistent state.
    await chat_message_repo.create(
        db,
        chat_session_id=session_id,
        role=MessageRole.USER,
        content=body.query,
    )
    await db.commit()

    # Start Langfuse trace
    trace_id: str = langfuse_tracing.start_trace(
        session_id=str(session_id),
        user_id=str(current_user.id),
        query=body.query,
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        from langchain_core.messages import HumanMessage  # noqa: PLC0415

        try:
            from langgraph.errors import GraphInterrupt  # noqa: PLC0415
        except ImportError:
            GraphInterrupt = None  # type: ignore[assignment,misc]

        config: dict[str, Any] = {"configurable": {"thread_id": str(session_id)}}
        initial_state: dict[str, Any] = {
            "messages": [HumanMessage(content=body.query)],
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

        final_answer = ""
        message_id = ""
        sources: list[Any] = []

        try:
            async for event in pipeline.astream_events(initial_state, config=config, version="v2"):
                kind = event["event"]

                if kind == "on_chat_model_stream":
                    token = event.get("data", {}).get("chunk", {})
                    if hasattr(token, "content") and token.content:
                        final_answer += token.content
                        yield ChatStreamEvent.delta(token.content).to_sse()

                elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                    output = event.get("data", {}).get("output", {})
                    final_answer = output.get("final_answer", final_answer)
                    sources = output.get("sources", sources)

        except GeneratorExit:
            # Client disconnected — persist partial message so the session has a record.
            # If the stream produced no real tokens, skip the insert; the
            # `is_partial=True` flag means "real tokens then aborted", not
            # "empty placeholder", and `chat_messages.content` is NOT NULL.
            if not final_answer:
                logger.warning(
                    "Chat stream aborted with empty final_answer for session=%s — "
                    "skipping partial persist",
                    session_id,
                )
                langfuse_tracing.end_trace(trace_id, output="[aborted]")
                return
            async with db_session_factory() as db:
                try:
                    await chat_message_repo.create(
                        db,
                        chat_session_id=session_id,
                        role=MessageRole.ASSISTANT,
                        content=final_answer,
                        is_partial=True,
                    )
                    await db.commit()
                except Exception:
                    logger.exception(
                        "Failed to persist partial message for session=%s", session_id
                    )
            langfuse_tracing.end_trace(trace_id, output="[aborted]")
            return

        except Exception as exc:  # noqa: BLE001
            # Check for GraphInterrupt first (if import succeeded)
            if GraphInterrupt is not None and isinstance(exc, GraphInterrupt):
                question = str(exc) if str(exc) else "Could you clarify your question?"
                yield ChatStreamEvent.clarification(question).to_sse()
                langfuse_tracing.end_trace(trace_id, output="[clarification]")
                return

            logger.exception("Chat pipeline error: %s", exc)
            yield ChatStreamEvent.error(message="An error occurred.", code="pipeline_error").to_sse()
            langfuse_tracing.end_trace(trace_id, output="", error=str(exc)[:200])
            return

        # Guard: pipeline ended with empty final_answer (e.g. generate_response
        # produced zero chunks, or guardrail_output early-returned). The DB
        # column `chat_messages.content` is NOT NULL — inserting None/'' would
        # raise IntegrityError, the bare except below would swallow it, and
        # the SSE stream would close without a terminal frame, locking the
        # frontend textarea. Emit an error event instead so the UI exits its
        # pending state. Mirrors the precedent in agent/nodes/persist.py:67.
        if not final_answer:
            logger.warning(
                "Chat pipeline ended with empty final_answer for session=%s — "
                "skipping persist and emitting error frame",
                session_id,
            )
            yield ChatStreamEvent.error(
                message="The assistant produced no response. Please try again.",
                code="empty_response",
            ).to_sse()
            try:
                langfuse_tracing.end_trace(trace_id, output="[empty]")
            except Exception:
                logger.exception(
                    "Failed to end langfuse trace for session=%s", session_id
                )
            return

        # Save assistant message and emit done event
        async with db_session_factory() as db:
            try:
                assistant_msg = await chat_message_repo.create(
                    db,
                    chat_session_id=session_id,
                    role=MessageRole.ASSISTANT,
                    content=final_answer,
                    is_partial=False,
                )
                message_id = str(assistant_msg.id)
                await db.commit()
            except Exception:
                # Don't silently swallow — log full stack and emit an error
                # frame so the frontend exits its pending state instead of
                # waiting forever for a terminal SSE event.
                logger.exception(
                    "Failed to persist assistant message for session=%s", session_id
                )
                yield ChatStreamEvent.error(
                    message="Failed to save the assistant response.",
                    code="persist_error",
                ).to_sse()
                try:
                    langfuse_tracing.end_trace(
                        trace_id, output=final_answer, error="persist_failed"
                    )
                except Exception:
                    logger.exception(
                        "Failed to end langfuse trace for session=%s", session_id
                    )
                return

        yield ChatStreamEvent.done(
            session_id=str(session_id),
            message_id=message_id,
            trace_id=trace_id,
            sources=sources,
        ).to_sse()
        langfuse_tracing.end_trace(trace_id, output=final_answer)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
