from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.deps import require_role
from src.core.redis import redis_ping
from src.models.user import User, UserRole
from src.schemas.health import WorkerHealthSummary
from src.services.worker_health_service import get_worker_health_summary

router = APIRouter()

AdminOnly = require_role(UserRole.admin)


@router.get("/health")
async def health_check() -> dict[str, str]:
    redis_ok = await redis_ping()
    status = "ok" if redis_ok else "degraded"
    return {
        "status": status,
        "version": "0.1.0",
        "redis": "ok" if redis_ok else "degraded",
    }


@router.get("/health/workers", response_model=WorkerHealthSummary)
async def get_worker_health(
    _: User = Depends(AdminOnly),
    db: AsyncSession = Depends(get_db),
) -> WorkerHealthSummary:
    """Return aggregated worker health event counts.  Admin-only."""
    return await get_worker_health_summary(db)
