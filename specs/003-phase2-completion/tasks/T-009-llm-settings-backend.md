# T-009: LLM Settings Backend (CRUD + Test)

- **Status**: Pending
- **Created**: 2026-04-21
- **Branch**: `003-phase2-completion`
- **User Story**: As an admin, I want to view, edit, and test the LLM configuration for each of the 10 pipeline stages so I can tune providers, models, temperature, and token limits per stage and verify connectivity before saving.
- **Requirement**: FR-021 (view/edit 10 stages), FR-022 (provider/model/key/temp/tokens), FR-023 (test connection), FR-024 (reflector toggle)
- **Priority**: P1

---

## 📋 Embedded Context

### Registry Standards (locked for this project)
| Key | Value |
|-----|-------|
| `architecture.pattern` | modular_monolith |
| `architecture.layers` | clean |
| `code_patterns.data_access` | repository |
| `code_patterns.dependency_injection` | container (dependency-injector IoC) |
| `code_patterns.error_handling` | exceptions |
| `code_patterns.validation_approach` | schema (Pydantic) |
| `database.tenancy_model` | single_tenant |
| `database.primary_key_type` | uuid |
| `database.migration_strategy` | versioned (Alembic) |
| `conventions.files` | snake_case (Python) |
| `conventions.variables` | snake_case |
| `conventions.classes` | PascalCase |
| `api.versioning` | /api/v1/ |
| `api.error_format` | rfc7807 |
| `api.pagination` | offset (limit/offset/total) |
| `backend.language` | python |
| `backend.framework` | fastapi |
| `backend.orm` | sqlalchemy (async) |
| `backend.auth_method` | jwt |
| `backend.auth_pattern` | rbac (admin/user) |
| `testing.unit_framework` | pytest |

### Domain Rules (backend-architect + python-pro)
- All services registered in `backend/src/core/container.py` via `dependency-injector`.
- All DB access through Repository classes — no raw SQL in services or routers.
- Alembic for all schema changes.
- Admin endpoints protected with `require_admin` dependency.
- RFC 7807 error responses.
- API keys stored encrypted (Fernet) — responses include only `api_key_hint` (last 4 chars), never the full key.
- `connection_config` and `file_storage_path` NEVER in API responses (not applicable here, but applies project-wide).

### API Context
- Base path: `/api/v1/admin/llm-settings`
- Auth: `require_admin` on every route
- Error envelope: RFC 7807 problem+json

### Feature Summary
Phase 2B admin experience: expose the 10-stage LLM configuration so admins can set provider/model/key/temperature/max_tokens per stage, toggle the reflector, and run a live test against the provider.

### Gate Criteria
- All 3 routes mount under `/api/v1/admin/llm-settings` and require admin auth.
- API key is never returned in plaintext — only `api_key_hint` (last 4 chars).
- `test_config` wraps the provider call in a Langfuse trace with `stage="config_test"`.
- Repository, service, and router are wired via `container.py`.

---

## 🎯 Objective

Deliver a clean-architecture admin backend for per-stage LLM configuration: `LLMConfigRepository` → `LLMConfigService` → FastAPI router with `GET` (list all 10), `PUT` (upsert one), and `POST /{stage}/test` (live connectivity check).

---

## 🛠️ Implementation Details

### Files to Create

1. **`backend/src/repositories/llm_config_repository.py`** — `LLMConfigRepository`
   - `async get_all() -> list[LLMConfiguration]` — fetch all rows from `llm_configurations`.
   - `async get_by_stage(stage: str) -> LLMConfiguration | None`.
   - `async upsert(stage: str, data: dict) -> LLMConfiguration` — insert or update by stage key.

2. **`backend/src/services/llm_config_service.py`** — `LLMConfigService`
   - Constants: `STAGES = ["schema_inspector", "clarification_detector", "query_analyzer", "source_router", "retrieval", "text_to_query", "synthesizer", "reflector", "input_guard", "output_guard"]`.
   - `async list_configs() -> list[LLMStageConfigPublic]` — return all stages; redact `api_key` to last 4 chars as `api_key_hint`; for stages with no row yet, return a default entry with `enabled=False`.
   - `async update_config(stage: str, data: UpdateLLMConfigRequest) -> LLMStageConfigPublic` — validate `stage in STAGES`; if `data.api_key` is None, preserve existing encrypted value; otherwise encrypt via injected Fernet and store; return redacted view.
   - `async test_config(stage: str) -> TestConnectionResult` — load config, decrypt key, instantiate the provider client based on `provider` (`openai|anthropic|ollama|azure_openai`), send a minimal ping (`messages=[{"role":"user","content":"ping"}]`, `max_tokens=5`), measure wall-clock latency, wrap in Langfuse trace with `stage="config_test"`, return `{"success": bool, "latency_ms": int, "message": str}`. Catch provider exceptions and map to `success=False` with the exception message.

3. **`backend/src/api/v1/admin/llm_settings.py`** — Router
   - `GET /` — `require_admin` → `LLMConfigService.list_configs()`.
   - `PUT /{stage}` — `require_admin`, body `UpdateLLMConfigRequest` → `LLMConfigService.update_config(stage, data)`.
   - `POST /{stage}/test` — `require_admin` → `LLMConfigService.test_config(stage)`.

### Files to Update

1. **`backend/src/core/container.py`** — Register `LLMConfigRepository` (providers.Factory with DB session) and `LLMConfigService` (providers.Factory with repo + Fernet + Langfuse client).
2. **`backend/src/api/v1/__init__.py`** (or `backend/src/main.py`) — `include_router(admin_llm_settings_router, prefix="/admin/llm-settings", tags=["admin","llm-settings"])`.

### Code / Logic Requirements

**Pydantic models (define in the router module or `backend/src/schemas/llm_config.py`):**

```python
from pydantic import BaseModel, Field

class UpdateLLMConfigRequest(BaseModel):
    provider: str  # openai | anthropic | ollama | azure_openai
    model: str
    api_key: str | None = None  # None = keep existing key
    base_url: str | None = None  # for Ollama / Azure
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, gt=0)
    enabled: bool = True

class LLMStageConfigPublic(BaseModel):
    stage: str
    label: str
    description: str
    provider: str
    model: str
    api_key_hint: str | None  # last 4 chars only
    base_url: str | None
    temperature: float
    max_tokens: int
    enabled: bool

class TestConnectionResult(BaseModel):
    success: bool
    latency_ms: int
    message: str
```

**Redaction rule:** `api_key_hint = api_key[-4:] if api_key else None`. Never include the full key in any response body or log.

**Errors (RFC 7807):**
- Unknown stage → 404 `{"type":"about:blank","title":"Stage not found","status":404}`.
- Provider exception during `test_config` → 200 OK with `success=False, message=<exc>` (do NOT leak the key).

---

## 🔌 Wiring Checklist (Web backend)

- [ ] `LLMConfigRepository` registered in `container.py`.
- [ ] `LLMConfigService` registered in `container.py` with Fernet + Langfuse client injected.
- [ ] Router included at `/api/v1/admin/llm-settings` in main app.
- [ ] All 3 routes guarded by `require_admin`.
- [ ] Langfuse trace emitted from `test_config` with `stage="config_test"`.
- [ ] No full `api_key` ever returned (grep the router response models).

---

## ✅ Verification

```bash
cd backend && python -c "from src.api.v1.admin.llm_settings import router; print('routes:', len(router.routes))"
```
Expected: prints `routes: 3` (or more).

Additional manual checks:
- `GET /api/v1/admin/llm-settings` with admin JWT returns 10 stage entries.
- `PUT /api/v1/admin/llm-settings/retrieval` with `api_key=null` preserves the stored key.
- `POST /api/v1/admin/llm-settings/retrieval/test` returns `{success, latency_ms, message}`.
- Non-admin JWT receives 403 on all 3 routes.

---

## 📝 Completion Log

- [ ] Repository implemented and unit-tested.
- [ ] Service implemented with redaction and Langfuse tracing.
- [ ] Router mounted and protected with `require_admin`.
- [ ] Container wiring updated.
- [ ] Verification command passes.
- [ ] Traceability: FR-021, FR-022, FR-023, FR-024 → this task → commit SHA _TBD_.
