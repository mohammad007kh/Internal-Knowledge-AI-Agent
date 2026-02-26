---
id: T-001
title: Project Scaffolding — Directory Structure, Tooling Configuration, and Monorepo Root
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
| State | React Context · TanStack Query · react-hook-form · Zod |
| Database | PostgreSQL 16 + pgvector · HNSW m=16 ef_construction=64 · UUID PKs · soft-delete + audit columns |
| Migrations | Alembic versioned |
| Background | Celery + Redis · Beat replicas=1 STRICT |
| File Storage | MinIO · presigned PUT pattern |
| Auth | JWT 15-min access + 7-day rotating httpOnly refresh cookie · bcrypt · RBAC (admin/user) |
| Encryption | Fernet (connection configs at rest) |
| AI Pipeline | LangGraph 8-node · interrupt() for clarification · SSE streaming |
| Tracing | Langfuse self-hosted · every pipeline run must emit a trace |
| Error Format | RFC 7807 Problem Details — all non-2xx API responses |
| Logging | Structured · INFO level · X-Request-ID correlation |
| Security | CORS strict · CSRF SameSite=Strict httpOnly · CSP moderate · rate-limit IP |
| UI | Dark mode · responsive · WCAG-AA · no animations · Lucide icons · Sonner toasts |
| Naming | snake_case vars/files/tables · PascalCase classes · SCREAMING_SNAKE_CASE constants |
| Commits | Conventional commits · branch pattern: NNN-description |
| Testing | pytest + httpx + Playwright · ≥80% coverage |
| Infrastructure | Docker Compose 9 services: frontend, backend, worker, beat, db, redis, minio, langfuse, langfuse-db |

### Domain Rules
- Connection strings and file paths MUST NEVER appear in user-facing output (FR-020)
- File size limit defined in `app_config.yaml`; default 50 MB (FR-035)
- Celery Beat MUST run with exactly 1 replica
- All passwords validated via `validate_password_policy()` (FR-034)

### API Context
Contracts: `specs/001-knowledge-ai-agent/contracts/` — auth.yaml, admin.yaml, chat.yaml, sources.yaml, users.yaml

### Feature Summary
Internal Knowledge AI Agent — single-tenant MVP. LangGraph 8-node pipeline; 9 Docker Compose services; FastAPI backend + Next.js 15 frontend; PostgreSQL 16 + pgvector; Celery + Redis for background jobs; MinIO for file storage; Langfuse for LLM tracing.

### Gate Criteria
- `make dev` — all 9 Docker Compose services start and pass healthchecks
- `make test` — pytest and tsc run without errors
- `make lint` — ruff and biome pass with zero errors

---

## 🎯 Objective

Establish the complete monorepo directory structure, language tooling configuration files (pyproject.toml, package.json, tsconfig.json), linting/formatting configs (ruff, biome), and the `.env.example` template. This is the scaffolding task — no application logic, only structure and config.

---

## 🛠️ Implementation Details

### Files to Create

| Path | Purpose |
|------|---------|
| `backend/pyproject.toml` | Python project config: dependencies, ruff, mypy, pytest settings |
| `backend/src/__init__.py` | Python package root |
| `backend/src/core/__init__.py` | Core package |
| `backend/src/api/__init__.py` | API package |
| `backend/src/models/__init__.py` | ORM models package |
| `backend/src/services/__init__.py` | Services package |
| `backend/src/repositories/__init__.py` | Repository pattern package |
| `backend/src/workers/__init__.py` | Celery workers package |
| `backend/src/config/__init__.py` | Config package |
| `backend/src/config/app_config.yaml` | Application config (file size limits, policy defaults) |
| `backend/tests/__init__.py` | Test package root |
| `backend/tests/unit/__init__.py` | Unit tests package |
| `backend/tests/integration/__init__.py` | Integration tests package |
| `frontend/package.json` | Node project config: Next.js 15, shadcn/ui, TanStack Query, react-hook-form, Zod, Lucide |
| `frontend/tsconfig.json` | TypeScript strict config with path aliases |
| `frontend/biome.json` | Biome linter + formatter config |
| `frontend/next.config.ts` | Next.js 15 config (App Router, strict mode) |
| `frontend/tailwind.config.ts` | Tailwind CSS v4 config with dark mode |
| `frontend/.env.example` | Frontend environment variable template |
| `frontend/src/app/layout.tsx` | Root App Router layout (providers, dark mode) |
| `frontend/src/app/globals.css` | Global CSS and CSS variables |
| `.env.example` | Monorepo root env template with ALL required variables |
| `.gitignore` | Comprehensive gitignore (Python, Node, env files, Docker) |
| `README.md` | Project README with setup instructions |

### Files to Update
- _(None — this is the initial scaffold task)_

### Code / Logic Requirements

**`backend/pyproject.toml`** must include:
- `[tool.ruff]` with `select = ["E", "F", "I", "UP"]` and `line-length = 120`
- `[tool.mypy]` with `strict = true`, `python_version = "3.12"`
- `[tool.pytest.ini_options]` with `asyncio_mode = "auto"` and `testpaths = ["tests"]`
- Dependencies: fastapi, sqlalchemy>=2, alembic, pydantic[email]>=2, python-jose[cryptography], passlib[bcrypt], celery[redis], langchain-core, langgraph, langfuse>=2, minio, cryptography, dependency-injector, httpx, structlog

**`backend/src/config/app_config.yaml`** must include:
```yaml
file_upload:
  max_size_bytes: 52428800  # 50 MB default — change here, NOT in .env
  supported_formats: [pdf, docx, xlsx, csv, txt, md]

bootstrap:
  admin_email_env: BOOTSTRAP_ADMIN_EMAIL
  admin_password_env: BOOTSTRAP_ADMIN_PASSWORD
```

**`.env.example`** must include ALL variables:
```
DATABASE_URL=postgresql+asyncpg://user:password@db:5432/knowledge_agent
REDIS_URL=redis://redis:6379/0
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=knowledge-agent
JWT_SECRET_KEY=<change-me-256bit>
JWT_REFRESH_SECRET_KEY=<change-me-256bit>
LANGFUSE_SECRET_KEY=<langfuse-sk>
LANGFUSE_PUBLIC_KEY=<langfuse-pk>
LANGFUSE_HOST=http://langfuse:3000
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=<change-me>
NEXT_PUBLIC_API_URL=http://localhost:8000
ENCRYPTION_KEY=<fernet-key-base64>
```

**`frontend/tsconfig.json`** must set `"strict": true` and path alias `"@/*": ["./src/*"]`.

---

## 🔌 Wiring Checklist

- [ ] `backend/pyproject.toml` includes all required dependencies
- [ ] `backend/src/config/app_config.yaml` defines `file_upload.max_size_bytes` (NOT .env)
- [ ] `.env.example` contains every variable used across all services
- [ ] `frontend/tsconfig.json` has strict mode and `@/` path alias
- [ ] `.gitignore` excludes `.env`, `__pycache__`, `.next`, `node_modules`

---

## ✅ Verification

```bash
# Verify Python tooling
cd backend && python -m pyproject.toml --version 2>/dev/null || python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))" && echo "pyproject.toml is valid"

# Verify backend package structure
python -c "import src.core; import src.api; import src.models; print('Backend packages OK')"

# Verify frontend TypeScript config
cd frontend && npx tsc --noEmit --version && echo "tsconfig valid"

# Verify app_config.yaml exists and has max_size_bytes
python -c "import yaml; c=yaml.safe_load(open('backend/src/config/app_config.yaml')); assert c['file_upload']['max_size_bytes']==52428800; print('app_config.yaml OK')"
```

**Success Criteria:**
- `pyproject.toml` parses without errors
- All `src/` sub-packages have `__init__.py`
- `app_config.yaml` contains `file_upload.max_size_bytes = 52428800`
- `.env.example` contains all 15+ required variables
- `frontend/tsconfig.json` has `strict: true`

---

## 📝 Completion Log

- [ ] Code implemented
- [ ] Tests passed
- [ ] Linter passed
- [ ] Wiring verified
- [ ] Integration verification passed
