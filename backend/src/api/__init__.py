from fastapi import APIRouter

from src.api.v1.health import router as health_router


def create_api_router() -> APIRouter:
    """Aggregate all versioned API routers into a single root router."""
    router = APIRouter()
    router.include_router(health_router, tags=["health"])
    return router


__all__ = ["create_api_router"]