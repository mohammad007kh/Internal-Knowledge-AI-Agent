---
id: T-002
title: Docker Compose 9-Service Configuration with Healthchecks
status: Not Started
created: 2026-02-25
phase: Phase 0 — Foundation
user_story: cross
requirements: []
---

## 📋 Embedded Context (READ THIS FIRST)

### Project Standards
| Standard | Value |
|---|---|
| Python | 3.12 |
| Backend | FastAPI · SQLAlchemy 2.x · Pydantic v2 · dependency-injector |
| Frontend | Next.js 15 App Router · shadcn/ui · Tailwind CSS |
| Background | Celery + Redis · Beat replicas=1 STRICT |
| File Storage | MinIO · presigned PUT pattern |
| Tracing | Langfuse self-hosted |
| Infrastructure | Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db |

### Domain Rules
- `beat` service MUST have `replicas: 1` — duplicate schedule hazard if scaled
- Auto-restart: `restart: on-failure` with max 3 attempts enforced by health_monitor.py at application level
- `langfuse-db` is a separate Postgres instance from the app `db`
- MinIO bucket name comes from `MINIO_BUCKET` env var

### Feature Summary
9-service Docker Compose stack. Frontend (Next.js, port 3000), Backend (FastAPI, port 8000), Worker (Celery), Beat (Celery Beat, replicas=1), DB (PostgreSQL 16 + pgvector, port 5432), Redis (port 6379), MinIO (ports 9000+9001), Langfuse (port 3001), Langfuse-DB (PostgreSQL, port 5433).

### Gate Criteria
- `docker compose up -d` — all 9 services reach healthy status
- `docker compose ps` — no service in "restarting" or "exited" state
- `make dev` completes with all healthchecks green

---

## 🎯 Objective

Create `docker-compose.yml` with all 9 services, network isolation, named volumes, healthchecks, and an `app_config.yaml` volume mount. Create `docker-compose.override.yml` for development (volume mounts and exposed ports). Each service has a correct healthcheck so dependent services wait for readiness.

---

## 🛠️ Implementation Details

### Files to Create

| Path | Purpose |
|------|---------|
| `docker-compose.yml` | Production-ready 9-service config |
| `docker-compose.override.yml` | Dev overrides: bind mounts, hot-reload, extra ports |
| `Makefile` | `make dev`, `make test`, `make lint`, `make build`, `make down` targets |

### Files to Update
- _(None — new files)_

### Code / Logic Requirements

**Service definitions (docker-compose.yml):**

```yaml
services:
  frontend:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on:
      backend:
        condition: service_healthy
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000"]
      interval: 30s
      timeout: 10s
      retries: 3

  backend:
    build: ./backend
    ports: ["8000:8000"]
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    env_file: .env
    volumes:
      - ./app_config.yaml:/app/app_config.yaml:ro
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  worker:
    build: ./backend
    command: celery -A src.workers.celery_app worker --loglevel=info
    depends_on:
      backend:
        condition: service_healthy
    env_file: .env

  beat:
    build: ./backend
    command: celery -A src.workers.celery_app beat --loglevel=info
    depends_on:
      - worker
    env_file: .env
    # NOTE: NEVER scale beat beyond 1 replica — duplicate schedule hazard
    deploy:
      replicas: 1

  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: knowledge_agent
      POSTGRES_USER: ${DB_USER:-postgres}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-postgres}
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-postgres}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports: ["9000:9000", "9001:9001"]
    environment:
      MINIO_ROOT_USER: ${MINIO_ACCESS_KEY:-minioadmin}
      MINIO_ROOT_PASSWORD: ${MINIO_SECRET_KEY:-minioadmin}
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 10s
      retries: 3

  langfuse:
    image: langfuse/langfuse:latest
    ports: ["3001:3000"]
    depends_on:
      langfuse-db:
        condition: service_healthy
    environment:
      DATABASE_URL: postgresql://langfuse:langfuse@langfuse-db:5432/langfuse
      NEXTAUTH_SECRET: ${LANGFUSE_SECRET_KEY}
      NEXTAUTH_URL: http://localhost:3001

  langfuse-db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: langfuse
      POSTGRES_USER: langfuse
      POSTGRES_PASSWORD: langfuse
    volumes:
      - langfuse_db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U langfuse"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  db_data:
  redis_data:
  minio_data:
  langfuse_db_data:

networks:
  default:
    name: knowledge_agent_network
```

**`docker-compose.override.yml`** must add:
- `backend`: bind mount `./backend/src:/app/src` for hot-reload
- `frontend`: bind mount `./frontend/src:/app/src` and `./frontend/public:/app/public`
- `worker` and `beat`: bind mount `./backend/src:/app/src`

**`Makefile`** targets:
```makefile
dev:
  docker compose up -d
down:
  docker compose down
test:
  cd backend && python -m pytest tests/ --cov=src --cov-report=term
  cd frontend && npx tsc --noEmit
lint:
  cd backend && ruff check src/ tests/
  cd frontend && npx biome check .
build:
  docker compose build
```

---

## 🔌 Wiring Checklist

- [ ] All 9 services defined in docker-compose.yml
- [ ] `beat` has `deploy.replicas: 1` comment explaining the constraint
- [ ] All services with dependencies use `condition: service_healthy`
- [ ] `backend` mounts `app_config.yaml` as read-only volume
- [ ] Named volumes declared in top-level `volumes` section
- [ ] `docker-compose.override.yml` adds bind mounts for hot-reload

---

## ✅ Verification

```bash
# Start all services and verify healthy
docker compose up -d
sleep 30
docker compose ps --format "table {{.Name}}\t{{.Status}}" | grep -v "healthy\|running"
# Above grep should return EMPTY (no unhealthy services)

# Verify all 9 services exist
docker compose ps | wc -l  # Should output 10 (header + 9 services)

# Verify backend healthcheck
curl -s http://localhost:8000/health | python -m json.tool
# Expected: {"status": "ok"}
```

**Success Criteria:**
- `docker compose ps` shows all 9 services with status `running` or `healthy`
- Zero services in `restarting` / `exited` / `unhealthy` state
- Backend responds on `localhost:8000/health`
- Frontend responds on `localhost:3000`

---

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring verified
- [ ] Integration verification passed
