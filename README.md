# Internal Knowledge AI Agent

A self-hosted RAG (retrieval-augmented generation) chat application for internal knowledge bases. Admins register **sources** (uploaded files, SQL databases, web URLs); users open a chat, pick which sources to scope to, and ask questions. The backend runs an 8-stage LangGraph pipeline that clarifies intent, rewrites the query for better retrieval, picks which sources to consult, fetches relevant chunks via pgvector cosine search (or generates safe SQL for database sources), then synthesizes an answer with inline citations. Every LLM call is configurable per-stage from the admin UI and traced in Langfuse.

**For a code-grounded walkthrough of how the agent actually works** (which nodes run, where the LLM enters, how sources are picked, what's wired vs aspirational), see [`docs/agentic-system.md`](docs/agentic-system.md).

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | Python 3.12 + FastAPI (modular monolith, clean architecture) |
| Agent Pipeline | LangChain + LangGraph (10-node, v2 optional, reflector optional) |
| Frontend | Next.js 15 (App Router) + shadcn/ui + Tailwind CSS v4 |
| Database | PostgreSQL 16 + pgvector |
| Jobs | Celery + Redis (beat: single replica only) |
| Observability | Langfuse 2 (self-hosted) |
| Object Storage | MinIO |
| Deployment | Docker Compose (10 services) |

## Prerequisites

- Docker ≥ 24.x and Docker Compose ≥ 2.24.x
- Python 3.12 (for local backend development)
- Node.js 20+ (for local frontend development)

## Quick Start

### 1. Clone and configure environment

```bash
git clone <repo-url>
cd "Internal Knowledge AI Agent"
cp .env.example .env
# Edit .env and fill in all required values
```

### 2. Start all services

```bash
docker compose up -d
```

Services start at:
- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Langfuse**: http://localhost:3001
- **MinIO Console**: http://localhost:9001

### 3. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

### 4. Log in

Use the bootstrap admin account credentials (set via `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` in `.env`).

## Local Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
uvicorn src.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend will rebuild automatically if you change `HOST_BACKEND_PORT` in `.env`:
```bash
docker compose build frontend
```

## Running Tests

### Backend

```bash
cd backend
pytest                         # all tests
pytest tests/unit              # unit tests only
pytest tests/integration       # integration tests only
pytest --cov=src --cov-report=html   # with coverage
```

### Frontend (E2E)

```bash
cd frontend
npx playwright test
```

## Docker Services

10 services run in Docker Compose:

1. **frontend** — Next.js app on port 3000 (configurable via `HOST_FRONTEND_PORT`)
2. **backend** — FastAPI on port 8000 (configurable via `HOST_BACKEND_PORT`)
3. **worker** — Celery task worker (processes async jobs)
4. **beat** — Celery Beat scheduler (single replica, **DO NOT scale** — duplicate scheduling = data corruption)
5. **db** — PostgreSQL 16 + pgvector on port 5432 (configurable via `HOST_DB_PORT`)
6. **redis** — Redis 7 on port 6379 (configurable via `HOST_REDIS_PORT`)
7. **minio** — Object storage API on port 9000 (configurable via `HOST_MINIO_API_PORT`)
8. **minio** — MinIO console on port 9001 (configurable via `HOST_MINIO_CONSOLE_PORT`)
9. **langfuse** — Observability UI on port 3001 (configurable via `HOST_LANGFUSE_PORT`)
10. **langfuse-db** — PostgreSQL 16 for Langfuse (internal, no external port)

## Agent Pipeline

The LangGraph pipeline (`backend/src/agent/`) processes every user message. **For full detail** including the node graph, what each stage does, and how sources are routed, see [`docs/agentic-system.md`](docs/agentic-system.md). High-level summary:

### v2 pipeline (default)

```
load_history → guardrail_input → check_clarification → query_analyzer → source_router
  → (retrieve_context | text_to_query)   ← parallel branch per source
  → generate_response → [reflector?] → format_response → guardrail_output → persist
```

8 of the 10 admin-configurable stages are honest LLM calls today: `input_guard`, `clarification_detector`, `query_analyzer`, `source_router`, `text_to_query`, `synthesizer`, `output_guard`, `reflector`. Each stage's model + temperature + custom prompt is independently configurable from `/admin/llm-settings`.

### Pipeline Configuration

- **`PIPELINE_V2_ENABLED`** (default: `true`) — Use the full 8-stage pipeline. Setting to `false` rolls back to a 4-stage v1 in ~30 seconds via backend restart (emergency escape hatch).
- **`PIPELINE_REFLECTOR_ENABLED`** (default: `false`) — Self-critic node that can trigger one corrective retry. Expensive (extra LLM call per query), OFF by default per Constitution.
- **`PIPELINE_REFLECTOR_MAX_RETRIES`** (default: `1`) — Max retries when the reflector flags an issue.

### Source connectors

| Source type | Status |
|---|---|
| `file_upload` (PDF / DOCX / TXT / MD via MinIO) | ✅ Shipped |
| `database` (Postgres via async SQLAlchemy, with SQL-safety check) | ✅ Shipped |
| `web_url` (single-page fetch with SSRF guard) | ✅ Shipped (recursive crawl deferred) |
| `confluence` / `sharepoint` | ⏸️ Stub classes — not exposed in admin UI |

## Project Structure

```
.
├── backend/
│   ├── src/
│   │   ├── agent/
│   │   │   ├── nodes/          # 10 LangGraph nodes
│   │   │   ├── prompts.py      # Prompt templates for all nodes
│   │   │   └── pipeline.py     # LangGraph state machine & routing
│   │   ├── agents/             # LLM initialization (GPT, etc.)
│   │   ├── api/v1/             # FastAPI route handlers
│   │   ├── config/             # App config, app_config.yaml
│   │   ├── connectors/         # Source integrations (Confluence, SharePoint, etc.)
│   │   ├── core/               # App factory, DI container, database, storage, logging
│   │   ├── middleware/         # HTTP middleware (logging, security headers)
│   │   ├── models/             # SQLAlchemy ORM models (User, Document, etc.)
│   │   ├── repositories/       # Data access layer (Repository pattern)
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   ├── services/           # Business logic
│   │   ├── tasks/              # Celery task base & definitions
│   │   ├── worker/             # Worker task implementations
│   │   ├── workers/            # Legacy worker code (deprecated)
│   │   └── main.py             # ASGI entrypoint
│   ├── tests/
│   │   ├── unit/               # Unit tests
│   │   └── integration/        # Integration tests
│   ├── alembic/                # Database schema migrations
│   └── pyproject.toml          # Dependencies, metadata
├── frontend/
│   ├── src/
│   │   └── app/
│   │       ├── (admin)/        # Admin routes: /admin
│   │       ├── (auth)/         # Auth routes: /login, /setup, /password-reset, /change-password
│   │       ├── (user)/         # User routes: /chat, /profile
│   │       └── layout.tsx      # Root layout
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── tsconfig.json
│   └── package.json
├── docker-compose.yml          # 10-service stack definition
├── .env.example                # Environment variable template
├── app_config.yaml             # App configuration (mounted as read-only in containers)
└── README.md
```

## Environment Variables

See [.env.example](.env.example) for the full reference. Key sections:

### Database & Cache

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | — | PostgreSQL connection (async, sqlalchemy+asyncpg) |
| `REDIS_URL` | — | Redis for caching and Celery broker |

### Object Storage (MinIO)

| Variable | Default | Purpose |
|----------|---------|---------|
| `MINIO_ENDPOINT` | `minio:9000` | MinIO API endpoint (internal) |
| `MINIO_ACCESS_KEY` | — | MinIO root user |
| `MINIO_SECRET_KEY` | — | MinIO root password |
| `MINIO_BUCKET` | `knowledge-agent` | S3 bucket for document storage |
| `MINIO_PUBLIC_ENDPOINT` | `localhost:9000` | Public URL for presigned downloads (overridden by compose) |

### Authentication & Encryption

| Variable | Default | Purpose |
|----------|---------|---------|
| `JWT_SECRET_KEY` | — | 256-bit key for JWT signing |
| `JWT_REFRESH_SECRET_KEY` | — | 256-bit key for refresh tokens |
| `ENCRYPTION_KEY` | — | Fernet key (base64) for encrypting connector configs |

### Bootstrap Admin Account

| Variable | Default | Purpose |
|----------|---------|---------|
| `BOOTSTRAP_ADMIN_EMAIL` | — | Initial admin email (auto-created on startup) |
| `BOOTSTRAP_ADMIN_PASSWORD` | — | Initial admin password |

### Langfuse Observability

| Variable | Default | Purpose |
|----------|---------|---------|
| `LANGFUSE_SECRET_KEY` | — | Langfuse secret key |
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse public key |
| `LANGFUSE_HOST` | `http://langfuse:3000` | Langfuse API endpoint |

### Celery Jobs

| Variable | Default | Purpose |
|----------|---------|---------|
| `CELERY_WORKER_CONCURRENCY` | `4` | Worker thread/process count |

### Account Lockout (Optional)

Layered on top of per-IP rate limiting:

```bash
LOCKOUT_ENABLED=true
LOCKOUT_MAX_FAILS=10
LOCKOUT_WINDOW_SECS=900        # 15 min sliding window
LOCKOUT_DURATION_SECS=1800     # 30 min lockout after threshold
```

See [.env.example](.env.example) for `LOCKOUT_REQUIRE_REDIS` (fail-closed behavior).

### Agent Pipeline (Optional)

```bash
# Enable v2 pipeline (clarify + query_analyzer + source_router)
PIPELINE_V2_ENABLED=true

# Enable self-critic (expensive, OFF by default)
PIPELINE_REFLECTOR_ENABLED=false
PIPELINE_REFLECTOR_MAX_RETRIES=1
```

### Host Port Mapping (Optional)

Override default ports to avoid clashes with other projects. Only uncomment the ports you want to shift:

```bash
HOST_FRONTEND_PORT=3000        # (default)
HOST_BACKEND_PORT=8000         # (requires frontend rebuild)
HOST_DB_PORT=5432              # (default)
HOST_REDIS_PORT=6379           # (default)
HOST_MINIO_API_PORT=9000       # (default)
HOST_MINIO_CONSOLE_PORT=9001   # (default)
HOST_LANGFUSE_PORT=3001        # (default)
```

**Note:** Changing `HOST_BACKEND_PORT` requires a frontend rebuild:
```bash
docker compose build frontend
```

## Key Development Patterns

### Repository Pattern

Data access is abstracted via repositories (`backend/src/repositories/`). Business logic depends on the repository interface, not the database directly. This enables easy mocking for tests and swapping storage layers.

```python
class UserRepository:
    async def find_by_id(self, user_id: str) -> User | None: ...
    async def create(self, user: User) -> User: ...
    async def update(self, user: User) -> User: ...
    async def delete(self, user_id: str) -> None: ...
```

### Immutability

All data objects are immutable. Updates return new copies, never modify in-place. This prevents hidden side effects and enables safe concurrency across Celery workers.

### API Response Envelope

All API responses use a consistent envelope:

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "metadata": { "total": 10, "page": 1, "limit": 50 }
}
```

### Error Handling

- Backend: detailed error context logged server-side, user-friendly messages in responses
- Frontend: errors caught and displayed via toast notifications
- Both: errors propagated up (never silently swallowed)

## Testing

Minimum 80% coverage required. Tests are organized by type:

- **Unit tests** — individual functions, services, repositories
- **Integration tests** — API endpoints, database operations
- **E2E tests** — critical user flows (Playwright)

Run tests:

```bash
# Backend
cd backend
pytest --cov=src --cov-report=html

# Frontend
cd frontend
npx playwright test
```

## Architecture Principles (from CLAUDE.md)

1. **Interface-First** — APIs and boundaries defined before implementation
2. **LLM Observability** — All LLM calls traced via Langfuse
3. **Connector Isolation** — Document sources pluggable via factory pattern
4. **Agent Pipeline Safety** — Query routing and policy enforcement built in
5. **Security by Default** — No secrets hardcoded, rate limiting on all endpoints
6. **Clean Architecture** — Dependencies point inward (core → services → api)
7. **Immutable Data** — No in-place mutations, functional patterns preferred

## Where to read next

- **[`docs/agentic-system.md`](docs/agentic-system.md)** — How the chat-to-answer flow actually works, every node explained, what's wired vs aspirational
- **[`docs/architecture-review-2026-04.md`](docs/architecture-review-2026-04.md)** — Five-expert review + 90-day prioritized roadmap (42 items)
- **[`docs/ai-models-and-embedders-design.md`](docs/ai-models-and-embedders-design.md)** — Design doc for the AI Models / Embedders admin feature
- **[`memory/constitution.md`](memory/constitution.md)** — Non-negotiable architectural principles
- **[`CLAUDE.md`](CLAUDE.md)** — Atomic Spec governance + project conventions

## Atomic Spec Framework

This project uses the **Atomic Spec** governance system for feature development. All major features go through `/atomicspec.specify` → `/atomicspec.plan` → `/atomicspec.tasks` → `/atomicspec.implement` phases with mandatory human-in-the-loop checkpoints.

See [CLAUDE.md](CLAUDE.md) and `specs/` for detailed governance.

## Contributing

Commits follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new feature
- `fix:` bug fix
- `refactor:` code reorganization (no behavior change)
- `docs:` documentation
- `test:` new tests or test improvements
- `chore:` build, tooling, dependencies

Example:
```
feat(agent): add reflector node for self-critique

Implements optional self-critic node in LangGraph pipeline.
Controlled via PIPELINE_REFLECTOR_ENABLED and 
PIPELINE_REFLECTOR_MAX_RETRIES env vars (off by default).
```

### Code Review

Before committing:
- Verify 80%+ test coverage
- Ensure no hardcoded secrets
- Check for SQL injection, XSS, CSRF vulnerabilities
- Validate all user inputs
- Run `docker compose up -d` and manually test critical flows

### Database Migrations

Use Alembic:

```bash
cd backend
alembic revision --autogenerate -m "add user roles"
alembic upgrade head
```

Migrations run automatically on backend startup. Test locally first:

```bash
docker compose exec backend alembic downgrade -1
docker compose exec backend alembic upgrade head
```

## License

Internal use only.
