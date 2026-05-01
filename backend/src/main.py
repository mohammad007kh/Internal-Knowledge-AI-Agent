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
from src.services.startup_seed import run_startup_seeding


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    import logging  # noqa: PLC0415

    log = logging.getLogger(__name__)

    # Startup: wire container, run migrations, bootstrap admin
    container.wire(packages=["src.api"])
    await init_redis()
    await bootstrap_admin()
    # Idempotent seeding — bootstrap AIModel/Embedder rows from env when the
    # tables are empty, then ensure every pipeline stage has a non-null
    # ai_model_id.  Wrapped internally so a misconfigured DB cannot crash
    # the app on boot — see services/startup_seed.py.
    try:
        await run_startup_seeding()
    except Exception:  # noqa: BLE001 - defence-in-depth
        log.warning("run_startup_seeding raised at startup", exc_info=True)
    yield
    # Shutdown: close pooled HTTP clients before tearing down the loop, then
    # close Redis.  Each ``aclose`` call is wrapped so a single failure does
    # not abort the rest of the shutdown sequence.
    for closer_name in ("ai_model_resolver", "embedding_service_factory"):
        try:
            singleton = getattr(container, closer_name)()
            await singleton.aclose()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            log.warning("lifespan shutdown: %s.aclose() failed", closer_name, exc_info=True)
    await close_redis()


def create_app() -> FastAPI:
    configure_logging()
    _is_dev = settings.ENVIRONMENT == "development"
    app = FastAPI(
        title="Knowledge AI Agent",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if _is_dev else None,
        openapi_url="/openapi.json" if _is_dev else None,
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
