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
# libmagic1: required by python-magic (file_upload_connector → MIME detection).
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev curl libmagic1 && \
    rm -rf /var/lib/apt/lists/*

# Create the unprivileged runtime user before copying the application.
# uid=1000 mirrors the frontend image's `nextjs` user pattern.
RUN groupadd -r appuser && useradd -r -g appuser -u 1000 appuser

# Install Python dependencies first (layer cache optimisation).
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application source.
COPY . .

# COPY runs as root by default — flip ownership to the runtime user so
# alembic / uvicorn can read the source tree without root privileges.
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Run migrations then start the ASGI server.
# exec hands PID 1 to uvicorn so it receives SIGTERM for graceful shutdown.
CMD alembic upgrade head && exec uvicorn src.main:app --host 0.0.0.0 --port 8000
