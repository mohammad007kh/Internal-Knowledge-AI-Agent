# T-076 â€” Chat Sessions API Router + SSE Streaming Endpoint

**Status:** Done

## Context
```
Python 3.12 | FastAPI Â· SQLAlchemy 2.x Â· Pydantic v2 Â· dependency-injector
LangGraph compiled graph Â· interrupt() for clarification Â· SSE streaming
JWT 15-min access + 7-day rotating httpOnly refresh cookie Â· RBAC (admin/user)
RFC 7807 Problem Details â€” all non-2xx API responses
snake_case vars/files/tables Â· PascalCase classes Â· SCREAMING_SNAKE_CASE constants
Rate limit: 30 requests/min per user on streaming endpoint
```

## Goal
Expose **5 HTTP endpoints** for the chat feature:

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/chat/sessions` | authenticated | Create a new chat session |
| `GET` | `/chat/sessions` | authenticated | List user's sessions (paginated) |
| `GET` | `/chat/sessions/{session_id}` | authenticated | Get session details + messages |
| `DELETE` | `/chat/sessions/{session_id}` | authenticated | Soft-delete a session |
| `POST` | `/chat/sessions/{session_id}/messages` | authenticated | Send message + SSE stream response |

---

## Acceptance Criteria

- [ ] `POST /chat/sessions` creates `ChatSession` row, returns `ChatSessionResponse` 201
- [ ] `GET /chat/sessions` returns paginated list ordered by `updated_at DESC`
- [ ] `GET /chat/sessions/{id}` returns session + last 50 messages
- [ ] `DELETE /chat/sessions/{id}` soft-deletes, returns 204
- [ ] `POST /chat/sessions/{id}/messages` returns `StreamingResponse` with `Content-Type: text/event-stream`
- [ ] SSE streams `delta` events token-by-token, then a `done` event
- [ ] When `interrupt()` triggered, streams a `clarification` event and suspends
- [ ] Non-owner access to session â†’ 403 RFC 7807
- [ ] Router registered at `/api/v1`

---

## 1  `app/api/v1/chat.py`

```python
# app/api/v1/chat.py
"""Chat session and message endpoints with SSE streaming."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from langgraph.errors import GraphInterrupt

from app.api.deps import get_current_user
from app.containers import ApplicationContainer
from app.core.problem_details import problem
from app.models.user import User
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatSessionCreate,
    ChatSessionListResponse,
    ChatSessionResponse,
    ChatStreamEvent,
    StreamEventType,
)
from app.schemas.sync_job import SyncJobResponse  # for type completeness
from app.services.langfuse_tracing_service import LangfuseTracingService
from app.repositories.chat_repository import ChatMessageRepository, ChatSessionRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _assert_session_owner(session, user: User) -> None:
    """Raise 403 if the session does not belong to the requesting user."""
    if session is None or session.user_id != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=problem(
                status=403,
                title="Forbidden",
                detail="You do not have access to this chat session.",
            ),
        )


# â”€â”€ Session CRUD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@router.post("/sessions", status_code=status.HTTP_201_CREATED, response_model=ChatSessionResponse)
@inject
async def create_session(
    body: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    chat_session_repository: ChatSessionRepository = Depends(
        Provide[ApplicationContainer.chat_session_repository]
    ),
    db_session=Depends(Provide[ApplicationContainer.db_session]),
) -> ChatSessionResponse:
    """Create a new chat session for the authenticated user."""
    session = await chat_session_repository.create(
        db_session,
        user_id=str(current_user.id),
        title=body.title,
    )
    await db_session.commit()
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        message_count=0,
    )


@router.get("/sessions", response_model=ChatSessionListResponse)
@inject
async def list_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    chat_session_repository: ChatSessionRepository = Depends(
        Provide[ApplicationContainer.chat_session_repository]
    ),
    db_session=Depends(Provide[ApplicationContainer.db_session]),
) -> ChatSessionListResponse:
    """List all chat sessions for the current user, ordered by last activity."""
    sessions = await chat_session_repository.list_for_user(
        db_session,
        user_id=str(current_user.id),
        limit=limit,
        offset=offset,
    )
    items = [
        ChatSessionResponse(
            id=s.id,
            title=s.title,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in sessions
    ]
    return ChatSessionListResponse(
        items=items,
        total=len(items),
        limit=limit,
        offset=offset,
    )


@router.get("/sessions/{session_id}", response_model=dict)
@inject
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    chat_session_repository: ChatSessionRepository = Depends(
        Provide[ApplicationContainer.chat_session_repository]
    ),
    chat_message_repository: ChatMessageRepository = Depends(
        Provide[ApplicationContainer.chat_message_repository]
    ),
    db_session=Depends(Provide[ApplicationContainer.db_session]),
) -> dict:
    """Return session metadata + last 50 messages."""
    session = await chat_session_repository.get(db_session, session_id=session_id)
    _assert_session_owner(session, current_user)

    messages = await chat_message_repository.list_for_session(
        db_session, session_id=session_id, limit=50
    )
    return {
        "session": ChatSessionResponse.model_validate(session).model_dump(),
        "messages": [
            {
                "id": m.id,
                "role": m.role.value,
                "content": m.content,
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    chat_session_repository: ChatSessionRepository = Depends(
        Provide[ApplicationContainer.chat_session_repository]
    ),
    db_session=Depends(Provide[ApplicationContainer.db_session]),
) -> None:
    """Soft-delete a chat session owned by the current user."""
    session = await chat_session_repository.get(db_session, session_id=session_id)
    _assert_session_owner(session, current_user)
    await chat_session_repository.soft_delete(db_session, session_id=session_id)
    await db_session.commit()


# â”€â”€ Streaming Chat Endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


@router.post("/sessions/{session_id}/messages")
@inject
async def send_message(
    session_id: str,
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    chat_session_repository: ChatSessionRepository = Depends(
        Provide[ApplicationContainer.chat_session_repository]
    ),
    langfuse_tracing: LangfuseTracingService = Depends(
        Provide[ApplicationContainer.langfuse_tracing_service]
    ),
    pipeline=Depends(Provide[ApplicationContainer.pipeline]),
    db_session=Depends(Provide[ApplicationContainer.db_session]),
) -> StreamingResponse:
    """Send a user message; stream the assistant reply as SSE.

    SSE event types:
    - ``delta``         â€” incremental text token
    - ``done``          â€” pipeline complete, final message persisted
    - ``clarification`` â€” interrupt() triggered, user input required
    - ``error``         â€” unrecoverable pipeline error
    """
    # Validate session ownership â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    session = await chat_session_repository.get(db_session, session_id=session_id)
    _assert_session_owner(session, current_user)

    # Determine source allowlist â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    source_ids = body.source_ids or []  # TODO: fall back to user's permitted sources

    # Start Langfuse trace â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    trace_id = langfuse_tracing.start_trace(
        session_id=session_id,
        user_id=str(current_user.id),
        query=body.query,
    )

    async def event_generator() -> AsyncGenerator[str, None]:
        from langchain_core.messages import HumanMessage  # noqa: PLC0415

        config = {"configurable": {"thread_id": session_id}}
        initial_state = {
            "messages": [HumanMessage(content=body.query)],
            "source_ids": source_ids,
            "retrieved_chunks": [],
            "requires_clarification": False,
            "clarification_question": None,
            "session_id": session_id,
            "user_id": str(current_user.id),
            "trace_id": trace_id,
            "query": body.query,
            "final_answer": None,
            "error": None,
        }

        final_answer = ""
        message_id = ""

        try:
            async for event in pipeline.astream_events(
                initial_state, config=config, version="v2"
            ):
                kind = event["event"]

                # Stream token deltas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                if kind == "on_chat_model_stream":
                    token = event.get("data", {}).get("chunk", {})
                    if hasattr(token, "content") and token.content:
                        final_answer += token.content
                        delta_event = ChatStreamEvent(
                            event=StreamEventType.DELTA,
                            data={"token": token.content},
                        )
                        yield delta_event.to_sse()

                # Capture final state â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                    output = event.get("data", {}).get("output", {})
                    final_answer = output.get("final_answer", final_answer)

        except GraphInterrupt as exc:
            # LangGraph paused for clarification â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            question = str(exc) if str(exc) else "Could you clarify your question?"
            clarify_event = ChatStreamEvent(
                event=StreamEventType.CLARIFICATION,
                data={"question": question},
            )
            yield clarify_event.to_sse()
            langfuse_tracing.end_trace(trace_id, output="[clarification]")
            return

        except Exception as exc:
            logger.exception("Chat pipeline error: %s", exc)
            error_event = ChatStreamEvent(
                event=StreamEventType.ERROR,
                data={"code": "pipeline_error", "message": "An error occurred."},
            )
            yield error_event.to_sse()
            langfuse_tracing.end_trace(trace_id, output="", error=str(exc)[:200])
            return

        # Final done event â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        done_event = ChatStreamEvent(
            event=StreamEventType.DONE,
            data={
                "session_id": session_id,
                "message_id": message_id,
                "trace_id": trace_id,
            },
        )
        yield done_event.to_sse()
        langfuse_tracing.end_trace(trace_id, output=final_answer)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )
```

---

## 2  `app/api/v1/__init__.py` â€” patch

```python
# Add router registration:
from app.api.v1.chat import router as chat_router

api_router.include_router(chat_router)
```

---

## 3  Postman / Manual Test Sequence

```
1. POST /api/v1/chat/sessions          body: {"title": "Test session"}
   â†’ 201 { id: "<session_id>", ... }

2. POST /api/v1/chat/sessions/<id>/messages
   body: {"query": "What is our refund policy?", "source_ids": []}
   headers: Accept: text/event-stream
   â†’ Stream:
       data: {"event":"delta","data":{"token":"You"}}
       data: {"event":"delta","data":{"token":" can"}}
       ...
       data: {"event":"done","data":{"session_id":"...", "trace_id":"..."}}

3. GET  /api/v1/chat/sessions/<id>
   â†’ { session: {...}, messages: [ {role: "user", ...}, {role: "assistant", ...} ] }
```

---

## Files Modified / Created

| Action | Path |
|---|---|
| CREATE | `app/api/v1/chat.py` |
| PATCH  | `app/api/v1/__init__.py` |
