from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI

from src.core.container import container
from src.core.logging import configure_logging
from src.api.middleware.logging_middleware import LoggingMiddleware
from src.api.v1.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: wire container, run migrations, bootstrap admin
    container.wire(packages=["src.api"])
    yield
    # Shutdown: close DB connections


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="Knowledge AI Agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(LoggingMiddleware)
    app.include_router(health_router, tags=["health"])
    return app


app = create_app()
