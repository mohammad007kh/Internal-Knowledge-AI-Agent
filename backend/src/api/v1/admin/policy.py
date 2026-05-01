"""Admin company-policy routes (T-010)."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import require_admin
from src.models.user import User
from src.repositories.company_policy_repository import CompanyPolicyRepository

router = APIRouter()


class UpdatePolicyRequest(BaseModel):
    content: str = Field(min_length=1)


class PolicyPublic(BaseModel):
    id: uuid.UUID | None = None
    content: str
    created_at: datetime | None = None


def _to_public(p) -> PolicyPublic:
    return PolicyPublic(id=p.id, content=p.rule_text, created_at=p.created_at)


@router.get("/", response_model=PolicyPublic)
async def get_policy(
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PolicyPublic:
    """Return the active policy, or an empty placeholder if none exists yet.

    The admin UI treats the company policy as a single editable document, so the
    "no rows yet" case is a normal first-run state — not an error. Returning an
    empty PolicyPublic keeps the editor working on a fresh database without a
    misleading 404.
    """
    repo = CompanyPolicyRepository(db)
    policy = await repo.get_active()
    if not policy:
        return PolicyPublic(id=None, content="", created_at=None)
    return _to_public(policy)


@router.put("/", response_model=PolicyPublic)
async def update_policy(
    body: UpdatePolicyRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> PolicyPublic:
    repo = CompanyPolicyRepository(db)
    policy = await repo.create_version(body.content, admin.id)
    return _to_public(policy)
