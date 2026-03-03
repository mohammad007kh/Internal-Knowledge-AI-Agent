---
id: T-010
title: Structured Logging Middleware + X-Request-ID Correlation
status: Done
created: 2026-02-25
phase: Phase 0 â€” Foundation
user_story: cross
requirements: []
priority: P1
depends_on: [T-004]
---

## ðŸ“‹ Embedded Context

**Standard**: Structured logging (JSON) Â· INFO level default Â· `X-Request-ID` correlation header  
**Library**: `structlog` with `structlog.stdlib.BoundLogger` interface  
**Integration**: FastAPI middleware + lifespan: inject `request_id` into every log record  
**Rule**: Never log secrets, tokens, passwords, or connection strings

---

## ðŸŽ¯ Objective

Configure structlog for JSON-formatted structured logging, add a FastAPI middleware that extracts or generates an `X-Request-ID` on every request and injects it into the structlog context, and ensure all subsequent log calls within a request include the correlation ID automatically.

---

## ðŸ› ï¸ Files to Create

| Path | Purpose |
|------|---------|
| `backend/src/core/logging.py` | structlog configuration, `get_logger()` helper |
| `backend/src/api/middleware/logging_middleware.py` | FastAPI middleware: X-Request-ID injection + request/response logging |

### Files to Update
- `backend/src/main.py` â€” add `LoggingMiddleware` to app
- `backend/src/core/__init__.py` â€” export `get_logger`

---

## Implementation

**`backend/src/core/logging.py`:**
```python
import logging
import structlog
from src.core.config import settings

def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_logger_name,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.LOG_LEVEL.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

def get_logger(name: str = __name__):
    return structlog.get_logger(name)
```

**`backend/src/api/middleware/logging_middleware.py`:**
```python
import uuid
import time
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from structlog.contextvars import bind_contextvars, clear_contextvars

logger = structlog.get_logger(__name__)

class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        clear_contextvars()
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception("unhandled_exception", method=request.method, path=request.url.path)
            raise
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=getattr(response, "status_code", 500),
                duration_ms=round(duration_ms, 2),
            )

        response.headers["X-Request-ID"] = request_id
        return response
```

**`backend/src/main.py` update (add after app creation):**
```python
from src.api.middleware.logging_middleware import LoggingMiddleware
from src.core.logging import configure_logging
# In create_app():
configure_logging()
app.add_middleware(LoggingMiddleware)
```

**Important constants to add to `backend/src/core/config.py`:**
```python
LOG_LEVEL: str = "info"
```

---

## ðŸ”Œ Wiring Checklist

- [ ] `configure_logging()` called before app starts (in `create_app` or lifespan)
- [ ] `LoggingMiddleware` added via `app.add_middleware()` â€” BEFORE error handlers
- [ ] Every response includes `X-Request-ID` header
- [ ] `get_logger()` importable from `src.core`
- [ ] Middleware never logs request body (PII risk)

---

## âœ… Verification

```bash
# Start backend and check log format
docker compose up -d backend
docker compose logs backend 2>&1 | head -5
# Expected: JSON objects like {"request_id": "...", "status_code": 200, "duration_ms": 1.2}

# Verify X-Request-ID is echoed back in response
curl -s -I -H "X-Request-ID: my-test-id" http://localhost:8000/health | grep X-Request-ID
# Expected: X-Request-ID: my-test-id

# Auto-generated when not provided
curl -s -I http://localhost:8000/health | grep X-Request-ID
# Expected: X-Request-ID: <some-uuid>
```

---

## ðŸ“ Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring verified
- [ ] Integration verification passed
