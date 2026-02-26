# ─── Backend Dockerfile ──────────────────────────────────────────────────────
# Builds the FastAPI backend image.  On startup the container runs
# `alembic upgrade head` (idempotent) before launching uvicorn so the
# database schema is always in sync with the application code.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required by asyncpg and other native libs.
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev curl && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cache optimisation).
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application source.
COPY . .

EXPOSE 8000

# Run migrations then start the ASGI server.
# exec hands PID 1 to uvicorn so it receives SIGTERM for graceful shutdown.
CMD alembic upgrade head && exec uvicorn src.main:app --host 0.0.0.0 --port 8000
