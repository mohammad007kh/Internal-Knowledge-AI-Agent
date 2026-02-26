from fastapi import APIRouter

from src.core.redis import redis_ping

router = APIRouter()


@router.get("/health")
async def health_check() -> dict[str, str]:
    redis_ok = await redis_ping()
    status = "ok" if redis_ok else "degraded"
    return {
        "status": status,
        "version": "0.1.0",
        "redis": "ok" if redis_ok else "degraded",
    }
