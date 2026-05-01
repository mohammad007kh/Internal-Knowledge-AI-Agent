"""Admin guardrail event routes (T-011)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import require_admin
from src.models.user import User
from src.repositories.guardrail_event_repository import GuardrailEventRepository

router = APIRouter()


class GuardrailEventListItem(BaseModel):
    id: uuid.UUID
    guard_type: str          # from direction
    action: str              # "blocked" / "logged" from blocked bool
    reason: str | None
    session_id: uuid.UUID | None
    created_at: datetime


class GuardrailEventDetail(GuardrailEventListItem):
    original_input: str       # from text


class GuardrailEventListResponse(BaseModel):
    items: list[GuardrailEventListItem]
    total: int
    limit: int
    offset: int


def _action_from_blocked(blocked: bool) -> str:
    return "blocked" if blocked else "logged"


def _to_list_item(e) -> GuardrailEventListItem:
    return GuardrailEventListItem(
        id=e.id,
        guard_type=e.direction,
        action=_action_from_blocked(e.blocked),
        reason=e.reason,
        session_id=e.session_id,
        created_at=e.created_at,
    )


def _to_detail(e) -> GuardrailEventDetail:
    return GuardrailEventDetail(
        id=e.id,
        guard_type=e.direction,
        action=_action_from_blocked(e.blocked),
        reason=e.reason,
        session_id=e.session_id,
        created_at=e.created_at,
        original_input=e.text,
    )


@router.get("/", response_model=GuardrailEventListResponse)
async def list_events(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    guard_type: Literal["input", "output"] | None = Query(None),
    action: Literal["blocked", "logged"] | None = Query(None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> GuardrailEventListResponse:
    repo = GuardrailEventRepository(db)
    blocked_filter: bool | None = None
    if action == "blocked":
        blocked_filter = True
    elif action == "logged":
        blocked_filter = False
    events, total = await repo.list_events(
        limit=limit,
        offset=offset,
        direction=guard_type,
        blocked=blocked_filter,
    )
    return GuardrailEventListResponse(
        items=[_to_list_item(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{event_id}", response_model=GuardrailEventDetail)
async def get_event(
    event_id: uuid.UUID,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> GuardrailEventDetail:
    repo = GuardrailEventRepository(db)
    event = await repo.get_by_id(event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "title": "Guardrail event not found",
                "status": 404,
                "type": "about:blank",
            },
        )
    return _to_detail(event)
