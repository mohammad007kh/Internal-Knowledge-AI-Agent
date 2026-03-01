"""Chat sessions API router — T-076."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import StreamingResponse

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

    return Container.db_session_factory()


def _get_chat_session_repo() -> ChatSessionRepository:
    from src.core.container import Container  # noqa: PLC0415

    return Container.chat_session_repo()


def _get_chat_message_repo() -> ChatMessageRepository:
    from src.core.container import Container  # noqa: PLC0415

    return Container.chat_message_repo()


def _get_pipeline() -> Any:
    from src.core.container import Container  # noqa: PLC0415

    return Container.pipeline()


def _get_tracing() -> LangfuseTracingService:
    from src.core.container import Container  # noqa: PLC0415

    return Container.langfuse_tracing_service()


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
    db_session_factory: Any = Depends(_get_db_session_factory),
    chat_session_repo: ChatSessionRepository = Depends(_get_chat_session_repo),
) -> ChatSessionResponse:
    """Create a new chat session for the authenticated user."""
    async with db_session_factory() as db:
        session_obj = await chat_session_repo.create(
            db,
            user_id=current_user.id,
            title=body.title,
        )
        return ChatSessionResponse.model_validate(session_obj)


@router.get("/sessions", response_model=ChatSessionListResponse)
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db_session_factory: Any = Depends(_get_db_session_factory),
    chat_session_repo: ChatSessionRepository = Depends(_get_chat_session_repo),
) -> ChatSessionListResponse:
    """List all chat sessions for the authenticated user."""
    async with db_session_factory() as db:
        sessions = await chat_session_repo.list_for_user(db, current_user.id)
        session_responses = [ChatSessionResponse.model_validate(s) for s in sessions]
        return ChatSessionListResponse(sessions=session_responses, total=len(session_responses))


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db_session_factory: Any = Depends(_get_db_session_factory),
    chat_session_repo: ChatSessionRepository = Depends(_get_chat_session_repo),
    chat_message_repo: ChatMessageRepository = Depends(_get_chat_message_repo),
) -> dict[str, Any]:
    """Retrieve a chat session with its last 50 messages."""
    async with db_session_factory() as db:
        session_obj = await chat_session_repo.get(db, session_id)
        _assert_session_owner(session_obj, current_user)

        messages = await chat_message_repo.list_for_session(db, chat_session_id=session_id)
        last_50 = messages[-50:]

        return {
            "session": ChatSessionResponse.model_validate(session_obj),
            "messages": [ChatMessageResponse.model_validate(m) for m in last_50],
        }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db_session_factory: Any = Depends(_get_db_session_factory),
    chat_session_repo: ChatSessionRepository = Depends(_get_chat_session_repo),
) -> Response:
    """Soft-delete a chat session belonging to the authenticated user."""
    async with db_session_factory() as db:
        session_obj = await chat_session_repo.get(db, session_id)
        _assert_session_owner(session_obj, current_user)

        await chat_session_repo.soft_delete(db, session_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db_session_factory: Any = Depends(_get_db_session_factory),
    chat_session_repo: ChatSessionRepository = Depends(_get_chat_session_repo),
    chat_message_repo: ChatMessageRepository = Depends(_get_chat_message_repo),
    pipeline: Any = Depends(_get_pipeline),
    langfuse_tracing: LangfuseTracingService = Depends(_get_tracing),
) -> StreamingResponse:
    """Stream an AI response for a user query within a chat session."""

    # Verify ownership
    async with db_session_factory() as db:
        session_obj = await chat_session_repo.get(db, session_id)
        _assert_session_owner(session_obj, current_user)

        # Persist the user message
        await chat_message_repo.create(
            db,
            chat_session_id=session_id,
            role=MessageRole.USER,
            content=body.query,
        )

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
        }

        final_answer = ""
        message_id = ""

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

        # Save assistant message and emit done event
        async with db_session_factory() as db:
            try:
                assistant_msg = await chat_message_repo.create(
                    db,
                    chat_session_id=session_id,
                    role=MessageRole.ASSISTANT,
                    content=final_answer,
                )
                message_id = str(assistant_msg.id)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to persist assistant message for session %s", session_id)

        yield ChatStreamEvent.done(
            session_id=str(session_id),
            message_id=message_id,
            trace_id=trace_id,
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
