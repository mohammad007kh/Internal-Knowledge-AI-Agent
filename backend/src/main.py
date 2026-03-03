from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.middleware.error_handler import register_exception_handlers
from src.middleware.logging_middleware import RequestIDMiddleware
from src.api.v1.health import router as health_router
from src.api.v1.router import api_v1_router
from src.core.bootstrap import bootstrap_admin
from src.core.config import settings
from src.core.container import container
from src.core.logging import configure_logging
from src.core.redis import close_redis, init_redis
from src.middleware.rate_limit import RateLimitMiddleware
from src.middleware.security_headers import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: wire container, run migrations, bootstrap admin
    container.wire(packages=["src.api"])
    await init_redis()
    await bootstrap_admin()
    yield
    # Shutdown: close DB connections, close Redis
    await close_redis()


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Knowledge AI Agent",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # ── Exception handlers (FIRST — before anything else) ──
    register_exception_handlers(app)

    # ── Middleware (outermost first) ──
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        SecurityHeadersMiddleware,
        is_https=settings.ENVIRONMENT == "production",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.FRONTEND_URL],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID", "X-CSRF-Token"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
    )

    # ── Routes ──
    app.include_router(health_router, tags=["health"])
    app.include_router(api_v1_router, prefix="/api/v1")

    return app


app = create_app()
