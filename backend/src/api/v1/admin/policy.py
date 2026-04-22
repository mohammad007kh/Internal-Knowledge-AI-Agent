"""Admin company-policy routes (T-010)."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.core.deps import require_admin
from src.models.user import User

router = APIRouter()


class UpdatePolicyRequest(BaseModel):
    content: str = Field(min_length=1)


class PolicyPublic(BaseModel):
    id: uuid.UUID
    content: str
    created_at: datetime


def _to_public(p) -> PolicyPublic:
    return PolicyPublic(id=p.id, content=p.rule_text, created_at=p.created_at)


@router.get("/", response_model=PolicyPublic)
async def get_policy(_admin: User = Depends(require_admin)) -> PolicyPublic:
    from src.core.container import Container

    repo = Container.company_policy_repo()
    policy = await repo.get_active()
    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "title": "No active policy",
                "status": 404,
                "type": "about:blank",
            },
        )
    return _to_public(policy)


@router.put("/", response_model=PolicyPublic)
async def update_policy(
    body: UpdatePolicyRequest,
    admin: User = Depends(require_admin),
) -> PolicyPublic:
    from src.core.container import Container

    repo = Container.company_policy_repo()
    policy = await repo.create_version(body.content, admin.id)
    return _to_public(policy)
