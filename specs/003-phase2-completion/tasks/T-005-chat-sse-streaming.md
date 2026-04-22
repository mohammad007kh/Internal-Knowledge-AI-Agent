# T-005: Chat SSE Streaming Endpoint

| Field | Value |
|---|---|
| **Status** | Pending |
| **Created** | 2026-04-21 |
| **Feature** | 003-phase2-completion |
| **Branch** | `003-phase2-completion` |
| **User Story** | US-2 |
| **Requirements** | FR-014 (streaming response), FR-015 (stop button), FR-016 (citations), FR-017 (clarification), FR-018 (guardrail blocked) |
| **Priority** | P0 |

---

## Embedded Context

This task file is self-contained. Read only this file, `specs/003-phase2-completion/index.md`, and `specs/003-phase2-completion/traceability.md` during implementation (Context Pinning).

### Registry Standards (MUST follow)

| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.data_access` | repository |
| `code_patterns.dependency_injection` | container (dependency-injector IoC) |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic) |
| `database.tenancy_model` | single_tenant |
| `database.primary_key_type` | uuid |
| `database.migration_strategy` | versioned (Alembic) |
| `database.naming_tables` | snake_case |
| `database.naming_columns` | snake_case |
| `conventions.files` | snake_case (Python), kebab-case (Next.js) |
| `conventions.variables` | snake_case (Python) |
| `conventions.classes` | PascalCase |
| `api.versioning` | url (/api/v1/) |
| `api.error_format` | rfc7807 |
| `backend.language` | python |
| `backend.runtime_version` | python:3.12 |
| `backend.framework` | fastapi |
| `backend.orm` | sqlalchemy (async) |
| `backend.auth_method` | jwt |
| `backend.auth_pattern` | rbac (admin/user) |
| `backend.job_queue` | celery + redis |
| `backend.sse_pattern` | fastapi_streaming_response |
| `testing.unit_framework` | pytest |
| `testing.integration_framework` | httpx |

### Domain Rules (MUST follow)

- All new services MUST be registered in `backend/src/core/container.py` and injected via FastAPI `Depends()`
- All database access goes through a Repository class — no raw SQL in services or routers
- Alembic migration required for every schema change — never modify models without a migration
- New backend routes protected with `get_current_user` (any auth) or `require_admin` (admin-only)
- RFC 7807 error responses: `{"detail": "...", "type": "...", "status": 400}`
- File bytes NEVER pass through FastAPI — use MinIO presigned PUT URLs
- Every LLM call wrapped with Langfuse tracing
- `connection_config` and `file_storage_path` MUST NEVER appear in API responses

### Hard Constraints

1. File bytes must NEVER pass through the FastAPI backend (MinIO presigned PUT)
2. **Every LLM call MUST be Langfuse-traced (Constitution §II)** ← primary constraint for this task
3. Celery Beat runs as a single replica — no duplicate scheduled jobs

---

## Objective

Implement `POST /api/v1/chat/sessions/{session_id}/messages` as a FastAPI `StreamingResponse` that pipes LangGraph pipeline events through Server-Sent Events, plus the supporting session CRUD endpoints. All LLM calls inside the pipeline remain Langfuse-traced.

---

## Implementation Details

### Files to Create

#### 1. `backend/src/schemas/chat.py`

```python
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatSessionCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    source_ids: list[str] = Field(default_factory=list)


class ChatSessionRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)


class ChatMessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)
    source_ids: list[str] = Field(default_factory=list)


class ChatSessionResponse(BaseModel):
    id: str
    title: str | None
    source_ids: list[str]
    created_at: str
    updated_at: str


class ChatMessagePublic(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    message_type: str
    is_partial: bool
    sources_cited: list[dict] | None
    created_at: str
```

### Files to Update

#### 2. `backend/src/api/v1/chat.py`

Add session CRUD + SSE streaming endpoint.

```python
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from src.api.deps import get_current_user
from src.core.container import Container
from src.schemas.chat import (
    ChatMessagePublic,
    ChatMessageRequest,
    ChatSessionCreateRequest,
    ChatSessionRenameRequest,
    ChatSessionResponse,
)
from src.services.chat_service import ChatService
from src.services.agent_pipeline_service import AgentPipelineService

logger = logging.getLogger(__name__)


def sse_event(event: str, data: dict) -> str:
    """Encode an SSE event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------------------------- Session CRUD ----------------------------

@router.post(
    "/sessions",
    response_model=ChatSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    body: ChatSessionCreateRequest,
    current_user=Depends(get_current_user),
    service: ChatService = Depends(lambda: Container.chat_service()),
) -> ChatSessionResponse:
    session = await service.create_session(
        user_id=current_user.id,
        title=body.title,
        source_ids=body.source_ids,
    )
    return _to_session_response(session)


@router.patch("/sessions/{session_id}", response_model=ChatSessionResponse)
async def rename_session(
    session_id: UUID,
    body: ChatSessionRenameRequest,
    current_user=Depends(get_current_user),
    service: ChatService = Depends(lambda: Container.chat_service()),
) -> ChatSessionResponse:
    session = await service.get_session_for_owner(session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    updated = await service.rename_session(session_id, body.title)
    return _to_session_response(updated)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: UUID,
    current_user=Depends(get_current_user),
    service: ChatService = Depends(lambda: Container.chat_service()),
) -> None:
    session = await service.get_session_for_owner(session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    await service.soft_delete_session(session_id)


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[ChatMessagePublic],
)
async def list_messages(
    session_id: UUID,
    limit: int = 50,
    offset: int = 0,
    current_user=Depends(get_current_user),
    service: ChatService = Depends(lambda: Container.chat_service()),
) -> list[ChatMessagePublic]:
    session = await service.get_session_for_owner(session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = await service.list_messages(session_id, limit=limit, offset=offset)
    return [_to_message_public(m) for m in messages]


# ---------------------------- SSE streaming ----------------------------

@router.post("/sessions/{session_id}/messages")
async def post_message_stream(
    session_id: UUID,
    body: ChatMessageRequest,
    request: Request,
    current_user=Depends(get_current_user),
    chat_service: ChatService = Depends(lambda: Container.chat_service()),
    pipeline: AgentPipelineService = Depends(
        lambda: Container.agent_pipeline_service()
    ),
) -> StreamingResponse:
    # Ownership check BEFORE we start the stream — so we can return 404 cleanly.
    session = await chat_service.get_session_for_owner(session_id, current_user.id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    allowed_source_ids = await chat_service.filter_allowed_sources(
        user_id=current_user.id,
        requested_source_ids=body.source_ids,
    )

    async def generator() -> AsyncGenerator[str, None]:
        user_msg = await chat_service.append_user_message(
            session_id=session_id,
            content=body.content,
            message_type="normal",
        )

        assistant_buffer: list[str] = []
        citations: list[dict] = []
        message_type = "normal"
        assistant_msg_id: str | None = None
        total_tokens = 0

        try:
            async for event in pipeline.stream(
                session_id=session_id,
                user_message_id=user_msg.id,
                user_content=body.content,
                source_ids=allowed_source_ids,
                user_id=current_user.id,
            ):
                # Abort if client disconnected.
                if await request.is_disconnected():
                    break

                kind = event.get("type")
                if kind == "token":
                    delta = event.get("delta", "")
                    assistant_buffer.append(delta)
                    total_tokens += 1
                    yield sse_event("token", {"delta": delta})
                elif kind == "citations":
                    citations = event.get("citations", [])
                    yield sse_event("citations", {"citations": citations})
                elif kind == "clarification_needed":
                    message_type = "clarification_request"
                    yield sse_event(
                        "clarification_needed",
                        {"question": event.get("question", "")},
                    )
                elif kind == "guardrail_blocked":
                    message_type = "guardrail_blocked"
                    yield sse_event(
                        "guardrail_blocked",
                        {"message": event.get("message", "Blocked by guardrail")},
                    )

            assistant_msg = await chat_service.append_assistant_message(
                session_id=session_id,
                content="".join(assistant_buffer),
                sources_cited=citations,
                message_type=message_type,
                is_partial=False,
            )
            assistant_msg_id = str(assistant_msg.id)
            yield sse_event(
                "done",
                {
                    "session_id": str(session_id),
                    "message_id": assistant_msg_id,
                    "total_tokens": total_tokens,
                },
            )
        except GeneratorExit:
            # Client aborted — persist partial message.
            await chat_service.append_assistant_message(
                session_id=session_id,
                content="".join(assistant_buffer),
                sources_cited=citations,
                message_type=message_type,
                is_partial=True,
            )
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Chat pipeline error: %s", exc)
            yield sse_event(
                "error",
                {"message": "Pipeline error. Please try again."},
            )

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------- Serialization helpers ----------------------------

def _to_session_response(session) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=str(session.id),
        title=session.title,
        source_ids=[str(s) for s in (session.source_ids or [])],
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


def _to_message_public(m) -> ChatMessagePublic:
    return ChatMessagePublic(
        id=str(m.id),
        session_id=str(m.session_id),
        role=m.role,
        content=m.content,
        message_type=m.message_type,
        is_partial=m.is_partial,
        sources_cited=m.sources_cited,
        created_at=m.created_at.isoformat(),
    )
```

**SSE event grammar** (stable contract for the frontend):

| Event | Payload |
|---|---|
| `token` | `{"delta": "<text chunk>"}` |
| `citations` | `{"citations": [{"ref": 1, "source_name": "...", "excerpt": "...", "page": null}]}` |
| `clarification_needed` | `{"question": "..."}` |
| `guardrail_blocked` | `{"message": "..."}` |
| `done` | `{"session_id": "...", "message_id": "...", "total_tokens": N}` |
| `error` | `{"message": "Pipeline error. Please try again."}` |

**Critical behaviors**:
- Ownership verified BEFORE streaming starts — 404 returned cleanly (not mid-stream).
- `source_ids` intersected with user's permitted sources via `ChatService.filter_allowed_sources`.
- User message persisted before streaming starts.
- Assistant message persisted on `done` with `is_partial=False`.
- On client abort (`GeneratorExit`): persist assistant message with `is_partial=True`.
- On exception: yield `error` event but do NOT crash the response.
- Langfuse tracing lives inside `AgentPipelineService.stream()` — unchanged.
- SSE headers include `Cache-Control: no-cache` and `X-Accel-Buffering: no` to defeat reverse-proxy buffering.

---

## Wiring Checklist (Web)

- [x] `backend/src/schemas/chat.py` created with request/response models
- [x] `POST /api/v1/chat/sessions` (create) added
- [x] `PATCH /api/v1/chat/sessions/{id}` (rename) added
- [x] `DELETE /api/v1/chat/sessions/{id}` (soft-delete) added
- [x] `GET /api/v1/chat/sessions/{id}/messages` (history) added
- [x] `POST /api/v1/chat/sessions/{session_id}/messages` SSE endpoint added
- [x] All routes protected by `get_current_user` + ownership check
- [x] `source_ids` intersected with permissions before pipeline
- [x] Partial-message persistence on client abort
- [x] Langfuse tracing preserved (lives inside pipeline service — unchanged)
- [ ] Chat router already registered in main `api_router` — no re-wiring needed
- [ ] No new migration (schema changes done in T-001)
- [ ] No new service class — `ChatService` / `AgentPipelineService` already in container

---

## Verification Command

```bash
cd backend && python -c "
from src.api.v1.chat import router
paths = [r.path for r in router.routes]
print('routes:', paths)
assert any('messages' in p for p in paths), 'missing messages route'
print('OK')
"
```

**Expected output:** Prints the list of routes including a `/sessions/{session_id}/messages` path, then `OK`.

---

## Completion Log

- [ ] `schemas/chat.py` created with all request/response Pydantic models
- [ ] `POST /sessions` creates a session (201) and returns `ChatSessionResponse`
- [ ] `PATCH /sessions/{id}` renames, owner-only, 404 for non-owner
- [ ] `DELETE /sessions/{id}` soft-deletes, owner-only, 204 on success
- [ ] `GET /sessions/{id}/messages` returns paginated history, owner-only
- [ ] `POST /sessions/{session_id}/messages` returns `StreamingResponse(media_type="text/event-stream")`
- [ ] SSE headers include `Cache-Control: no-cache` and `X-Accel-Buffering: no`
- [ ] Ownership checked BEFORE streaming begins (404 returned pre-stream)
- [ ] `source_ids` intersected with user-permitted sources
- [ ] User message persisted before pipeline runs
- [ ] All 6 SSE event types emitted correctly (`token`, `citations`, `clarification_needed`, `guardrail_blocked`, `done`, `error`)
- [ ] Client abort → assistant message persisted with `is_partial=True`
- [ ] Pipeline exception → `error` event yielded, no 500 crash
- [ ] Langfuse tracing inside pipeline service preserved (no change required)
- [ ] Verification command prints routes and `OK`
