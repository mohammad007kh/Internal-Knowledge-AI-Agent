# AI Models & Embedders — Management Feature Design

**Status:** Draft v1 — synthesized from 8 expert consultations (Phase 1 architect/UX/backend/security + Phase 2 provider catalog/pgvector/migration/test-and-capabilities)
**Owner:** TBD
**Last updated:** 2026-04-25

---

## 1. Executive Summary

Today every pipeline stage on `/admin/llm-settings` carries inline `(provider, model, api_key, temperature, max_tokens)`. The same OpenAI key is re-entered N times, model identifiers are typed by hand, and there is **no first-class concept of an Embedder**. The embedding model used at retrieval is hardcoded (`text-embedding-3-small`, 1536 dims) and a single environment variable governs every chunk in the database.

This design adds two admin CRUD surfaces — `/admin/ai-models` and `/admin/embedders` — and rewires `/admin/llm-settings` so each stage references an AI Model record by id from a searchable dropdown. Behind the scenes it also fixes three pre-existing critical defects:

1. `_encrypt_value` in `LLMConfigService` is a no-op stub — API keys are stored in plaintext today (see [§9 Security](#9-security)).
2. `chunk_repository.similarity_search` queries with `<->` (L2 distance) but the HNSW index is built `vector_cosine_ops` — the index is currently unused and queries fall back to sequential scan ([§6](#6-vector-storage--similarity-search)).
3. `LLMConfigService` is dead code — `pipeline.py` and `generate.py` use module-level constants and ignore the table entirely ([§4 Pipeline rewire](#4-pipeline-rewire)).

## 2. Goals & Non-Goals

### v1 goals
- Admins can register, list, edit, delete LLM endpoint records on `/admin/ai-models`.
- Admins can register, list, edit, delete embedder endpoint records on `/admin/embedders`.
- `/admin/llm-settings` becomes a searchable dropdown of AI Model records per stage; per-stage `temperature` / `max_tokens` / `custom_prompt` overrides remain.
- Each Source has a pinned Embedder (initially the legacy `text-embedding-3-small` row), enforced as immutable after first chunk is written.
- All API keys encrypted at rest using project-standard Fernet (matching `SourceService` pattern).
- Pipeline reads stage AI Model from the database at runtime via `AIModelResolver` (replacing hardcoded constants).
- Embeddings written/read via `EmbeddingServiceFactory` keyed by embedder record (not env var).
- Test-connection endpoints (pre-save plaintext + post-save record-bound).
- Admin audit log entries for every create/update/delete on these tables.

### v1 non-goals (deferred to v1.1)
- **Multiple active embedders simultaneously.** v1 enforces "one active embedder per deployment" via partial unique index. Switching the active embedder requires a re-index batch job; per-source heterogeneous embedders is a v1.1 concern.
- **Provider-family lockstep across stages: explicitly NOT enforced.** LLMs and embedders are independently selectable; cross-provider chains (e.g. GPT-4o stage A → Claude stage B → corpus indexed by Voyage) are first-class. There is no correctness coupling between LLM-to-LLM text passing and the indexing embedder — see [§6.5 Cross-Embedder Consistency Policy](#65-cross-embedder-consistency-policy).
- **Heterogeneous embedding dimensions.** `chunks.embedding vector(1536) NOT NULL` stays. Embedders with `dimensions != 1536` can be registered but cannot be activated until v1.1 ships per-embedder partitioned chunk storage.
- **Cost dashboards & usage metrics** beyond what `last_test_at` exposes.
- **Provider OAuth flows / Vertex / Bedrock** — covered by `openai-compatible` for now.
- **Per-stage API key overrides** — one key per AI Model record. If two stages need different keys for the same provider+model, register two AI Model rows.
- **Nightly capability probe job** — capabilities come from a baked-in metadata table.

## 3. Data Model

Three new tables + three modified columns. SQL types use Postgres canonical names.

### `ai_models`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | `gen_random_uuid()` default |
| `name` | VARCHAR(150) NOT NULL UNIQUE | Human label, e.g. `"GPT-4o Prod"` |
| `provider` | VARCHAR(64) NOT NULL | See [§5 Provider catalog](#5-provider-catalog) |
| `base_url` | VARCHAR(500) | NULL = use provider default |
| `model_id` | VARCHAR(200) NOT NULL | e.g. `gpt-4o-mini`, `claude-sonnet-4-5` |
| `api_key_encrypted` | BYTEA | Fernet ciphertext — never null in production |
| `extra_config` | JSONB DEFAULT '{}' | Provider-specific (Azure: deployment_name, api_version) |
| `default_temperature` | REAL DEFAULT 0.7 | |
| `default_max_tokens` | INT DEFAULT 2048 | |
| `capabilities` | JSONB DEFAULT '{}' | `{function_calling, vision, json_mode, streaming, max_context_tokens, input_cost_per_1m, output_cost_per_1m}` |
| `is_active` | BOOLEAN DEFAULT true | Soft-disable without delete |
| `last_test_at` | TIMESTAMPTZ | |
| `last_test_status` | VARCHAR(16) | `ok` / `failed` / `never` |
| `last_test_error` | VARCHAR(500) | Truncated, key-redacted |
| `created_at`, `updated_at` | TIMESTAMPTZ | |
| `created_by` | UUID FK→`users(id)` | Audit |

Indexes: `UNIQUE (provider, base_url, model_id, COALESCE(extra_config->>'deployment_name',''))` to prevent duplicates while allowing two Azure deployments of the same model.

### `embedders`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `name` | VARCHAR(150) NOT NULL UNIQUE | |
| `provider` | VARCHAR(64) NOT NULL | |
| `base_url` | VARCHAR(500) | |
| `model_id` | VARCHAR(200) NOT NULL | e.g. `text-embedding-3-small`, `voyage-3` |
| `api_key_encrypted` | BYTEA | |
| `extra_config` | JSONB DEFAULT '{}' | |
| `dimensions` | INT NOT NULL CHECK (dimensions BETWEEN 64 AND 4096) | Validated against pgvector column |
| `max_input_tokens` | INT | For chunk-size sanity checking |
| `is_active` | BOOLEAN DEFAULT false | See active-embedder constraint below |
| `last_test_at`, `last_test_status`, `last_test_error` | | |
| `created_at`, `updated_at`, `created_by` | | |

Constraints:
- `UNIQUE (provider, base_url, model_id, dimensions)`.
- **Partial unique index** `CREATE UNIQUE INDEX one_active_embedder ON embedders((is_active)) WHERE is_active = true` — exactly one active embedder at any time (v1 invariant; relaxed in v1.1).

### `admin_audit_log` (new)
| Column | Type | Notes |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `admin_user_id` | UUID FK→`users(id)` | |
| `action` | VARCHAR(32) | `create` / `update` / `delete` / `test` |
| `resource_type` | VARCHAR(32) | `ai_model` / `embedder` / `llm_setting` |
| `resource_id` | UUID | |
| `ip_address` | INET | |
| `metadata` | JSONB | Diff or context, **never the API key** |
| `created_at` | TIMESTAMPTZ | |

### Modified tables
- **`llm_configurations`**: drop `provider`, `model_name`, `api_key_encrypted`. Add `ai_model_id UUID REFERENCES ai_models(id) ON DELETE RESTRICT`. Keep `slot_name`, `temperature`, `max_tokens`, `custom_prompt`, `is_default`, `source_id`.
- **`sources`**: add `embedder_id UUID NOT NULL REFERENCES embedders(id) ON DELETE RESTRICT`.
- **`chunks`**: add `embedder_id UUID NOT NULL REFERENCES embedders(id) ON DELETE RESTRICT`. Index `ix_chunks_embedder_id`. The `embedding vector(1536) NOT NULL` column **stays unchanged** in v1; only embedders with `dimensions = 1536` can become active.

### Cascade behavior
- AI Models / Embedders use `ON DELETE RESTRICT` from referencing rows. The DELETE endpoint returns `409 Conflict` with the list of referencing resources; admins must reassign before deletion. Soft-delete (`is_active = false`) is the alternative.

## 4. Pipeline Rewire

### 4.1 `AIModelResolver` (new singleton)
```python
class AIModelResolver:
    async def resolve(stage: StageEnum) -> AIModelClient: ...
    def invalidate(): ...  # admin endpoint pokes this on update
```
`AIModelClient` = immutable record `(provider, model_id, temperature, max_tokens, http_client, capabilities)`. The underlying `AsyncOpenAI` (or other) client is cached per `(provider, base_url, api_key_hash)` tuple — clients are reusable HTTP pools.

A 60-second TTL cache holds the `(stage_id → AIModelClient)` mapping. Admin updates take effect on the next request after TTL. An internal `POST /api/v1/admin/ai-models/invalidate-cache` poke endpoint exists for surgical refresh.

### 4.2 Affected stages (5 today + future)
Existing LLM-using nodes: `generate_response`, `check_clarification`, `guardrail_input`, `guardrail_output`, plus any new stages.

Each receives the resolver via `pipeline.build_pipeline(resolver, ...)` and calls `client = await resolver.resolve("generate_response")` at node entry. Module-level `_MODEL`, `_TEMPERATURE`, `_MAX_TOKENS` constants in `generate.py` are deleted.

### 4.3 `EmbeddingServiceFactory` (new)
```python
class EmbeddingServiceFactory:
    async def for_active() -> EmbeddingService           # v1: returns the singleton active
    async def for_source(source_id: UUID) -> EmbeddingService   # v1: also returns active (one-embedder invariant)
    async def for_embedder(embedder_id: UUID) -> EmbeddingService
```

`EmbeddingService.__init__` now takes `(api_key, model_id, dimensions, base_url)`. The factory caches by `embedder_id`. Validates `len(vector) == self.dimensions` at write time.

### 4.4 Hot-reload
TTL-based caching (60s) with optional explicit invalidation via admin endpoint. No hot-reload across pipeline graph rebuilds — graph is rebuilt per request only if the resolver returns a different model (it doesn't, by design).

## 5. Provider Catalog

`backend/src/services/provider_catalog.py` exposes a static `dict[str, ProviderSpec]` and a public endpoint `GET /api/v1/admin/providers` that the frontend hydrates.

Each entry carries a `family_tag` used for **soft pairing hints only** (never validated server-side):

```python
PROVIDER_FAMILY = {
  "openai": "openai", "azure-openai": "openai",
  "anthropic": "anthropic",            # no native embedder
  "google-gemini": "google",
  "voyage": "voyage", "cohere": "cohere",
  "ollama": "local", "openai-compatible": "compatible",
}
PROVIDERS_WITHOUT_NATIVE_EMBEDDER = {"anthropic"}  # suppresses cross-family warning
```

Used for the cosmetic "Often paired with…" UX hint in the embedder picker. See [§6.5](#65-cross-embedder-consistency-policy).

### v1 LLM providers
| Key | Display | Default base_url | Auth | Suggested models | Extra fields |
|---|---|---|---|---|---|
| `openai` | OpenAI | `https://api.openai.com/v1` | Bearer | gpt-4.1, gpt-4o, gpt-4o-mini, o3, o4-mini | `organization_id?`, `project_id?` |
| `anthropic` | Anthropic | `https://api.anthropic.com/v1` | x-api-key + version header | claude-opus-4-5, claude-sonnet-4-6, claude-haiku-4-5 | `anthropic_version` (default `2023-06-01`) |
| `google-gemini` | Google Gemini (AI Studio) | `https://generativelanguage.googleapis.com/v1beta` | x-goog-api-key | gemini-2.5-pro, gemini-2.5-flash | — |
| `azure-openai` | Azure OpenAI | _composed_ | api-key | _deployment names_ | `azure_endpoint`, `deployment_name`, `api_version` |
| `ollama` | Ollama (local) | `http://ollama:11434/v1` | none | llama3.3, qwen2.5, mistral-nemo | — |
| `openai-compatible` | OpenAI-compatible | _required_ | Bearer (optional) | _freeform_ | — |

### v1 Embedder providers
| Key | Models (native dims) | Configurable dims |
|---|---|---|
| `openai` | text-embedding-3-small (1536), 3-large (3072), ada-002 (1536) | yes (3-small, 3-large) |
| `google-gemini` | gemini-embedding-001 (3072), text-embedding-004 (768) | yes |
| `voyage` | voyage-3-large (1024), voyage-3 (1024), voyage-3-lite (512), voyage-code-3 (1024) | partial |
| `cohere` | embed-v4.0 (1536), embed-english-v3.0 (1024), embed-multilingual-v3.0 (1024) | yes (v4 only) |
| `azure-openai` | _deployment-driven_ | yes |
| `ollama` | nomic-embed-text (768), mxbai-embed-large (1024), bge-m3 (1024) | no |
| `openai-compatible` | freeform | user-declared |

**Deferred:** Vertex AI, AWS Bedrock, HuggingFace TEI (TGI is covered by openai-compatible), Anthropic embeddings (don't exist).

## 6. Vector Storage & Similarity Search

### 6.1 v1 invariant: single active embedder
- `embedders.is_active = true` is partial-unique → at most one active row.
- Admin UI rejects activating an embedder whose `dimensions != 1536` until v1.1 ships per-dim partitioned chunks.
- A "Switch active embedder" admin action triggers a Celery re-embed batch job; the activation is atomic on completion.

### 6.2 Critical pre-existing bug to fix in this work
`backend/src/repositories/chunk_repository.py:85` uses `embedding <-> :qvec` (L2 distance) against an HNSW index built `vector_cosine_ops`. Result: index is unused, sequential scan. Fix as part of this PR — change operator to `<=>` (cosine).

### 6.3 v1 retrieval query
```python
# retrieve.py (pseudocode)
embedder = await embedder_repo.get_active()
query_vec = await embedding_factory.for_embedder(embedder.id).embed_query(q)
# enforce v1 invariant
chunks = await chunk_repo.similarity_search(
    source_ids=allowlist,
    query_vec=query_vec,
    embedder_id=embedder.id,   # defensive — also protects v1.1 transition
    limit=k,
)
```
SQL:
```sql
SELECT c.id, c.source_id, c.chunk_text, c.embedding <=> :qvec AS score
FROM chunks c
WHERE c.source_id = ANY(:source_ids)
  AND c.embedder_id = :embedder_id
ORDER BY score ASC
LIMIT :limit;
```

### 6.4 Two-step query for small allowlists
For `source_ids` allowlists smaller than ~2000 chunks, sequential scan beats HNSW post-filter. Branch in `similarity_search`: prefetch `count(*)` for the allowlist; if < 2000, sequential scan. Else HNSW with post-filter. Document in code; revisit numbers based on EXPLAIN ANALYZE.

### 6.5 Cross-Embedder Consistency Policy

**Why it matters (the only correctness rule):** cross-model embedding spaces are not aligned. Querying corpus-X with embedder-Y returns *silently wrong* results — pgvector happily computes cosine distance between any two same-dimension vectors, no error raised. The system degrades to near-random retrieval, invisible to monitoring. The single-active-embedder invariant is the *only* hard rule; everything else is operational convenience.

**Common misconception:** "If stages use different LLMs they need shared embedders." False. LLMs read plain text from each other; tokens are not embedded vectors and need no alignment. GPT-4o → Claude → Gemini in a chain has zero embedder cost. Provider lockstep across stages is therefore explicitly NOT enforced.

**Hard constraints (DDL-enforced):**

```sql
-- chunks and sources both reference embedders with ON DELETE RESTRICT
CREATE UNIQUE INDEX one_active_embedder ON embedders((is_active)) WHERE is_active = true;
ALTER TABLE embedders ADD CONSTRAINT embedders_dim_range CHECK (dimensions BETWEEN 64 AND 4096);
CREATE INDEX ix_chunks_embedder_id ON chunks(embedder_id);
```

No FK from `ai_models` to `embedders` — they are orthogonal axes.

**Soft warnings (UX hint, never blocked):**

| Surface | Trigger | Message | Suppressed when |
|---|---|---|---|
| `/admin/embedders` activate | `embedder.family != active_llm_family` | "Active answer-generator LLM is `anthropic`. Anthropic has no native embedder; common pairings: voyage, cohere, openai." | LLM provider in `PROVIDERS_WITHOUT_NATIVE_EMBEDDER` |
| `/admin/llm-settings` EditStageDialog | Picked AI model family ≠ active embedder family AND LLM has native embedder | "Most teams pair `openai` LLMs with `openai` embedders for billing/key consistency." | LLM provider in `PROVIDERS_WITHOUT_NATIVE_EMBEDDER` |

**Not** shown on `/admin/sources` create — embedder is system-active, not a per-source choice in v1.

**Activation state machine:**

```
[draft] --activate--> [validating] --ok--> [reembedding] --ok--> [active]
                            |                      |
                            v fail                 v fail
                       [draft]              [rollback] (prior active restored)
```

Activation rejections (HTTP 409):
- `DIMENSION_LOCKED_V1` — target dimensions != 1536 (v1.1 lifts).
- `UNTESTED_EMBEDDER` — `last_test_status != "ok"` within last 24h.
- `ACTIVATION_IN_PROGRESS` — another reembed job running.
- `BLOCKED_ACTIVE` (on DELETE) — embedder is active.
- `BLOCKED_REFERENCED` (on DELETE) — chunks still reference it.

**Dry-run preview:** `GET /api/v1/admin/embedders/{id}/activate-preview` → `{chunks_to_reembed, estimated_seconds, estimated_api_cost_usd}`. Cheap (single COUNT + per-provider rate constant).

**Atomic swap (Celery job):**
1. Validate (dim, test status, dry-run cost) — record into `embed_progress(job_id, last_chunk_id, batch_count, started_at)`.
2. Snapshot `prior_active_id`. Old active stays `is_active=true` throughout — queries keep working.
3. Write new vectors to `chunks_staging` in 10k batches; commit per batch with `last_chunk_id` checkpoint.
4. Resumable: on worker crash, `SELECT MAX(last_chunk_id) WHERE job_id=...` and continue.
5. Final commit (single tx): UPDATE chunks SET embedding+embedder_id from staging; flip `is_active` flags; insert audit row; COMMIT.
6. Failure (3 batch retries): DELETE staging rows; prior active untouched; job state=failed.

Beat single-replica rule (CLAUDE.md) prevents concurrent runs.

**Stage–embedder coupling check:** Inspected `backend/src/agent/nodes/`. Only `retrieve.py` touches embeddings (always via `embedder_repo.get_active()`). `clarify`, `generate`, `guardrail`, `history`, `persist` do no in-flight similarity. No `STAGE_EMBEDDER_REQUIREMENTS` needed for v1. If a future reranker stage queries the corpus directly, it must use the active embedder; if it only ranks LLM-generated drafts among themselves, it has no coupling.

**Audit metadata** on `action="activate"`:
```json
{
  "prior_active_embedder_id": "...",
  "target_embedder_id": "...",
  "chunks_reembedded": 184213,
  "duration_seconds": 612,
  "job_id": "celery-...",
  "dry_run_estimate": {"chunks": 184000, "seconds": 600},
  "cross_family_warning_acknowledged": true,
  "active_llm_families_at_activation": ["openai", "anthropic"]
}
```
New sub-action `warning_dismissed` records `{surface, llm_family, embedder_family, dismissed_by}` to measure noise.

## 7. API Surface

All under `/api/v1/admin/*` with `require_admin` dependency.

### `/api/v1/admin/ai-models`
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/` | — (query: `?q=&provider=&active=`) | `{items[], total, limit, offset}` |
| POST | `/` | `AIModelCreate` | `AIModelPublic` |
| GET | `/{id}` | — | `AIModelPublic` |
| PATCH | `/{id}` | `AIModelUpdate` (api_key omitted = preserve) | `AIModelPublic` |
| DELETE | `/{id}` | — | `204` or `409 {referenced_by}` |
| POST | `/test-connection` | `{provider, model_id, api_key, base_url?, extra_config?}` | `{ok, latency_ms, error?}` (does not persist) |
| POST | `/{id}/test-connection` | — | `{ok, latency_ms, error?}` (updates `last_test_*`) |
| POST | `/invalidate-cache` | — | `204` |
| GET | `/{id}/usage` | — | `{stages: [], chat_messages_count}` |

### `/api/v1/admin/embedders`
Mirrors `/ai-models` plus:
- `POST /{id}/activate` — atomic: kicks off re-embed batch job, sets target embedder's `is_active = true` on completion. Returns a `job_id`. Rejects with 409 codes `DIMENSION_LOCKED_V1` / `UNTESTED_EMBEDDER` / `ACTIVATION_IN_PROGRESS`.
- `GET /{id}/activate-preview` — dry-run: `{chunks_to_reembed, estimated_seconds, estimated_api_cost_usd}`. No state change.
- `dimensions` is read-only on PATCH.

### `/api/v1/admin/llm-settings` (rewired)
- `GET /` returns 10 stages, each enriched with `ai_model: {id, name, provider, model_id, capabilities}` plus stage overrides.
- `PUT /{stage}` body: `{ai_model_id: UUID, temperature?, max_tokens?, custom_prompt?}`. No more inline provider/model/api_key.
- `POST /{stage}/test` resolves the linked AI Model and calls its credentials.

### `/api/v1/admin/providers` (new, static catalog)
- `GET /` returns the full provider catalog (LLM + embedder).

### Sources
- `POST /api/v1/sources` adds **required** `embedder_id`. Defaults to the active embedder's id if omitted.
- `PATCH /api/v1/sources/{id}` rejects `embedder_id` change once `chunks_count > 0` with `409 {message: "Re-index required"}`.

## 8. Frontend Pages

All under `(admin)/admin/`.

### 8.1 `/admin/ai-models` — `AiModelsPage.tsx`
- **Listing**: shadcn `DataTable`. Columns: Name, Provider (Badge), Model ID (mono, truncated), Base URL, API key (`••••• ····1234`), Last test (relative time + dot), Used by (count → Sheet), Updated. Right-side `Sheet` for create/edit.
- **Create flow** (Sheet): Identity (Name*, Description), Connection (Provider* select → defaults populate, Base URL*, Model ID combobox, API key `type=password`), Generation defaults (collapsible Advanced). `Test connection` button next to Save (encouraged not required).
- **Edit flow**: same Sheet. API key is read-only mask + "Replace API key" toggle.
- **Delete flow**: `AlertDialog` with usage check. Block hard delete if `usage_count > 0` — offer "Reassign references…" (dropdown) or "Archive" (soft).

### 8.2 `/admin/embedders` — `EmbeddersPage.tsx`
Same structure with extra columns Dimensions, Active (single yes/no), In-use (sources count). Create form includes `dimensions` (read-only after creation). Activate action: `AlertDialog` warning that all chunks must be re-indexed; submit triggers Celery job, shows progress in-page.

### 8.3 `/admin/llm-settings` (rewired) — keep `LlmSettingsPage.tsx`
- 10 `StageCard` grid stays. Each card shows **AI Model badge** linking to its detail.
- `EditStageDialog` replaces inline provider/model/api_key with `AiModelPicker.tsx` (shadcn `Command` + `Popover`). Two-line rows: name + provider Badge / model_id muted + tested dot. Search filters across name + model_id + provider.
- **Capability filtering**: incompatible models (e.g. `source_router` requires `function_calling`) shown disabled-with-tooltip ("Requires function_calling — `gpt-4o-mini` supports this"). Sort: compatible first, by `input_cost_per_1m` ascending.
- **No filtering on embedder provider.** The picker treats LLM and embedder as orthogonal — only capability mismatches block selection. Cross-provider pairings show a soft hint ("Most teams pair `openai` LLMs with `openai` embedders") but never disable.
- **Empty state**: zero AI Models → inline `Card` with `CpuIcon` + CTA → `/admin/ai-models?new=1`.

### 8.4 Sources — small additions
- `EmbedderPicker.tsx` on Source create/edit. Defaults to active embedder. Locked with warning once `chunks_count > 0`.

### 8.5 Sidebar nav
Group three under collapsible `AI ▸ (AI Models, Embedders, LLM Settings)` in `nav-config.ts`. Icons: `CpuIcon`, `Layers`, `SlidersHorizontal`. If group-nav isn't already supported, ship as flat siblings and add the group in iteration 2.

## 9. Security

### 9.1 Encryption
- **All API keys at rest** use `cryptography.fernet.Fernet(settings.ENCRYPTION_KEY)`. New shared helper at `backend/src/core/crypto.py` — every service imports from there.
- The current `_encrypt_value` stub at `backend/src/services/llm_config_service.py:163-174` is replaced by the real helper as part of this work. A one-time data migration re-encrypts existing rows: try-decrypt; on `InvalidToken` treat as legacy plaintext and re-encrypt with real Fernet.

### 9.2 API responses
- GET endpoints **never** return plaintext API keys. They return `api_key_last4` (4 chars) and `api_key_set: true|false`.
- PATCH endpoints accept `api_key: null | undefined` to mean "preserve existing". The frontend's "Replace API key" toggle controls whether the field is sent.

### 9.3 Test connection
- Both endpoints exist (plaintext form and record-bound). Plaintext-form endpoint **never persists** the key. Record-bound endpoint updates `last_test_at`/`last_test_status`/`last_test_error`.
- Fixed-format error messages — never embed `str(exc)` directly. `_scrub` redacts the literal key but is fragile against structured exception attributes.

### 9.4 Rate limiting
- Dedicated rate limit on test endpoints: **10 requests per 60 s per admin user** (per-user, not per-IP, since admins behind shared NAT must not collide). Apply in `backend/src/middleware/rate_limit.py`.

### 9.5 Audit log
- Every create/update/delete/activate/test on `ai_models` / `embedders` / `llm_configurations` writes one `admin_audit_log` row. Metadata JSONB: action params with API keys redacted.

### 9.6 Logging hygiene
- Override `to_dict()` and `__repr__` on `AIModel`, `Embedder`, and existing `LLMConfiguration` to omit `api_key_encrypted`.

### 9.7 Cascade discipline
- All FK references to `ai_models`/`embedders` use `ON DELETE RESTRICT`. The frontend's delete flow uses the `/usage` endpoint to surface blockers and offer reassignment.

## 10. Migration & Deployment

Three Alembic revisions + 6 deployment steps. Single environment flag `AI_MODELS_V2`.

### 10.1 Revisions
1. **R1 — additive schema** (`0023_ai_models_embedders.py`):
   - Create `ai_models`, `embedders`, `admin_audit_log`.
   - Add `sources.embedder_id NULL`, `chunks.embedder_id NULL`, `llm_configurations.ai_model_id NULL`. Indexes.
   - Add `last_test_at`, `last_test_status`, `last_test_error` columns to `ai_models` and `embedders`.

2. **R2 — backfill** (`0024_backfill_ai_models.py`, data-only):
   - Insert `embedders` row `legacy-openai-1536` (provider=`openai`, model_id=`text-embedding-3-small`, dimensions=1536, api_key from `settings.OPENAI_API_KEY` Fernet-encrypted, `is_active=true`).
   - Insert one `ai_models` row per distinct `(provider, model_name, api_key)` tuple in `llm_configurations`.
   - `UPDATE sources SET embedder_id = <legacy>` batched by 10k rows.
   - `UPDATE chunks SET embedder_id = <legacy>` batched by 10k rows.
   - `UPDATE llm_configurations SET ai_model_id = <matching>`.
   - **Encryption migration in same revision**: for each `llm_configurations.api_key_encrypted`, try-decrypt with Fernet; on failure (legacy plaintext stub), decode as UTF-8 and re-encrypt with real Fernet.
   - Fix HNSW operator mismatch: drop and recreate `chunks_embedding_hnsw_idx` if the migration audit reveals the existing one is wrong (or just fix `chunk_repository.similarity_search` to use `<=>`).

3. **R3 — tighten** (`0025_ai_models_constraints.py`):
   - `SET NOT NULL` on the three new FKs.
   - Drop `llm_configurations.provider`, `model_name`, `api_key_encrypted` (after one release cycle of stable v2 — defer to a later R4 if needed).

### 10.2 Deployment order
1. **Deploy A** (code-only): ship Fernet helper, `AIModelResolver`/`EmbeddingServiceFactory` with env-fallback paths, `AI_MODELS_V2=false`. New code is dormant. Rolling restart.
2. **Deploy B**: `alembic upgrade head` runs R1. Additive — no restart needed.
3. **Deploy C**: run R2. Low-traffic window. No restart.
4. **Deploy D**: set `AI_MODELS_V2=true`. Rolling restart of API + worker; restart `beat` last (single-replica per project rules). Watch error rate 30 min.
5. **Deploy E**: run R3 (tighten). No restart.
6. **Deploy F (cleanup, +1 release)**: delete fallback code paths and the `AI_MODELS_V2` env var.

### 10.3 Rollback
- Code break under V2: flip flag back to `false`, restart. Schema and data preserved.
- Schema break in R1: `alembic downgrade -1`. Additive — safe.
- Schema break post-R3: harder; legacy columns are gone. Mitigate by keeping `llm_configurations.api_key_encrypted` for one extra release cycle as dead storage — only drop after a week of stable V2.

## 11. Capabilities & Stage Requirements

`backend/src/services/provider_model_metadata.py` (constant) holds capability defaults indexed by `(provider, model_id)`. On `POST /ai-models`, the service looks up the entry and prefills `capabilities`. Admins can override via PATCH. Unknown `(provider, model_id)` → empty `{}` capabilities; admin must fill manually.

```python
STAGE_REQUIREMENTS = {
  "source_router":     {"function_calling": True, "min_context_tokens": 8000},
  "query_classifier":  {"json_mode": True,        "min_context_tokens": 4000},
  "retrieval_grader":  {"json_mode": True,        "min_context_tokens": 4000},
  "answer_generator":  {"streaming": True,        "min_context_tokens": 16000},
  "summarizer":        {"min_context_tokens": 32000},
}
def is_compatible(caps: dict, stage: str) -> tuple[bool, list[str]]: ...
```

**Frontend dropdown UX:** show all models, disable incompatible with explanatory tooltip ("Requires function_calling — `gpt-4o-mini` supports this"). Sort: compatible by ascending `input_cost_per_1m`, incompatible disabled below.

## 12. Open Questions / Risks

1. **Per-stage vs per-model API key.** v1 puts the key on the AI Model record. If two stages need the same `(provider, model_id)` with different cost-center keys, register two AI Model rows with different names. Acceptable v1 tradeoff.
2. **Capability staleness.** Baked-in metadata table needs manual updates when providers ship new models. Watch for staleness; consider a nightly probe job in v1.1.
3. **Chat message audit trail.** Today `chat_messages` doesn't snapshot which AI Model produced it. With `ON DELETE RESTRICT`, that means a chat session's referenced model can never be deleted while messages exist. v1 accepts this; v1.1 considers snapshotting `ai_model_id` on each message and switching to `ON DELETE SET NULL` for historical messages.
4. **MSSQL driver.** `mssql+aioodbc://` may not be installed; AI Model registration succeeds but sync fails at runtime. Out of scope here — flagged in the recent DB consolidation work.
5. **Multi-tenant isolation.** This system is single-tenant. If multi-tenancy is added, AI Models/Embedders need a `tenant_id` column.
6. **Vertex AI / Bedrock.** Deferred. If a customer needs them, `openai-compatible` against the appropriate shim (Vertex's OpenAI-compat endpoint, LiteLLM proxy) is the v1 escape hatch.
7. **Cross-family warning telemetry.** Track `warning_dismissed` audit rows for 30 days post-launch. If dismissal rate >70%, the warning is noise — demote to docs only.
8. **Reranker coupling.** No reranker stage exists today. If/when one is added, document whether it queries the corpus (must use active embedder) or only ranks LLM-generated drafts among themselves (no coupling).

## 13. Implementation Plan

The implementation is large enough to ship in three sequential PRs:

- **PR 1 — Foundation**: shared crypto helper, audit log table, AIModel + Embedder schemas/models/repos, R1 migration. CRUD endpoints (without test-connection). Test-connection plaintext endpoint. Provider catalog endpoint. **No** pipeline rewire yet.
- **PR 2 — Pipeline rewire**: `AIModelResolver`, `EmbeddingServiceFactory`, rewire `pipeline.py` + 5 nodes + `GuardrailService` + sync_source. Behind `AI_MODELS_V2=false` initially. R2 backfill + encryption migration. Fix `<->` → `<=>` operator. Activate the flag.
- **PR 3 — Frontend + tighten**: `/admin/ai-models` page, `/admin/embedders` page, rewire `/admin/llm-settings`, sidebar nav. Source pages embedder picker. R3 tighten + cleanup of legacy columns.

Each PR is independently deployable and reviewable.

---

## Appendix A — Reviewed File References

Backend:
- `backend/src/models/llm_configuration.py:13-40`
- `backend/src/models/source.py`
- `backend/src/models/chunk.py:27,48-50`
- `backend/src/repositories/llm_config_repository.py`
- `backend/src/repositories/chunk_repository.py:77-94` (HNSW operator bug)
- `backend/src/services/llm_config_service.py:13,163-174` (encryption stub)
- `backend/src/services/embedding_service.py:20-21,35-37`
- `backend/src/services/source_service.py` (Fernet pattern reference)
- `backend/src/services/connector_service.py:33` (Fernet pattern reference)
- `backend/src/api/v1/admin/llm_settings.py:107-114,150,163,189,202,249`
- `backend/src/agent/pipeline.py:48-136`
- `backend/src/agent/nodes/generate.py:20-22,73,100`
- `backend/src/agent/nodes/retrieve.py:25-112`
- `backend/src/core/container.py:100,150-191`
- `backend/src/core/config.py:35,37`
- `backend/src/core/deps.py:98-110`
- `backend/src/middleware/rate_limit.py:26,38-41`
- `backend/src/models/base.py:15-16` (to_dict leak risk)
- `backend/src/tasks/sync_source.py:108-151`
- `backend/alembic/versions/0007_documents_chunks.py:141,147-158,163-168`
- `backend/alembic/versions/0014_llm_configurations.py:22-78`

Frontend:
- `frontend/src/app/(admin)/admin/llm-settings/page.tsx`
- `frontend/src/app/(admin)/admin/llm-settings/_components/EditStageDialog.tsx`
- `frontend/src/components/dashboard/nav-config.ts`
