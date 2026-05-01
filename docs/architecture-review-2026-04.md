# Architecture Review — 2026-04

**Date:** 2026-04-25
**Scope:** Production-readiness assessment of Internal Knowledge AI Agent at the close of Phase 2.
**Method:** Five parallel expert reviews — architect, ai-engineer, backend-architect, ui-ux-designer, security-reviewer — each grounded in code reads + current best-practice references.
**Branch reviewed:** `003-phase2-completion` @ `830960b`.

---

## TL;DR

The product is **mid-flight on the AI-Models-V2 rewire** and is **production-aware but not production-ready**. The runtime LangGraph pipeline is materially smaller than what the PRD, admin UI, and design docs claim — five of the ten configured stages are dead rows that no node consumes. Citations show UUIDs because of a key-name mismatch. A live OpenAI key sits in `backend/.env` (gitignored, but in the Docker build context). Repository session lifetime is ungoverned in several routers and will exhaust the connection pool under load. Backend containers run as root. There is no account lockout, no user/source audit trail, and no Fernet key rotation path.

The good news: the new `AIModelResolver` / `EmbeddingServiceFactory` / connector registry / pgvector cosine fix / Fernet helper / audit redaction are all **textbook** and should be the template for everything that comes next. The product is two focused weeks away from "production blocker list cleared," then a month from "production quality."

---

## Top 10 fix-now items (consolidated CRITICAL across all teams)

1. **Rotate the live OpenAI key in `backend/.env`** and add a `backend/.dockerignore` so the build context can never copy it. The file is gitignored but lives on disk in the Docker build context. *(Security — C-1)*
2. **Wire the missing pipeline nodes** (`query_analyzer`, `source_router`, `text_to_query`, `reflector`) and replace heuristic `check_clarification` with the configured LLM. Admin UI has shown 10 stage configs since AI-Models-V2 landed; only 5 are read. *(Architect §2.CRITICAL, AI-Engineer §1)*
3. **Fix citations**: `agent/nodes/persist.py:42` reads `chunk.get("document_title")` / `page_number` keys that `retrieve.py:76-85` never produces. Hydrate from `chunks_by_id[cid].metadata_` (already populated at sync time). One added dict lookup; immediate UX win. *(AI-Engineer §5)*
4. **Fix stage-name mismatch**: `generate.py:27` resolves `"generate_response"` but the seeded admin slot is `"synthesizer"`. Admin temperature/prompt edits never apply because `_fallback_active` silently masks the miss. Same for guardrail nodes. *(AI-Engineer §5)*
5. **Replace `MemorySaver` with `PostgresSaver`** for LangGraph checkpointing. In-process memory blocks horizontal scaling and drops in-flight clarifications on every restart. *(Architect §2.HIGH, item #2)*
6. **Unify repository session pattern** and stop calling `Container.xxx_repo()` mid-request. Several routers open ungoverned sessions that are never closed, leaking connections. *(Backend §2.CRITICAL items 1–2)*
7. **Add account lockout on `/api/v1/auth/login`**: per-email-hash sliding window, lockout after N failed attempts. Per-IP only is bypassable by botnets; current limit (`20/60s`) is permissive. *(Security — C-3, M-5)*
8. **Run backend containers as non-root**: `groupadd -r appuser && useradd -r -g appuser appuser` + `USER appuser` in `backend/Dockerfile`. Frontend already does this. *(Security — C-4)*
9. **Parameterise hardcoded `langfuse-db` credentials** in `docker-compose.yml` and remove the `${DB_PASSWORD:-postgres}` fallback so a missing env var fails loud, not weak. *(Security — C-2, M-2, M-3)*
10. **Tighten `chunks.embedder_id` to `NOT NULL`** after backfill and complete R3 of the AI-Models-V2 migration. Drop legacy `LLMConfiguration` columns. Closes the half-shipped rewire. *(Architect §2.HIGH item #4)*

---

## Roadmap by horizon

### Now (next 2 weeks) — production blockers

| # | Item | Effort | Owner area |
|---|---|---|---|
| 1 | Rotate exposed OpenAI key + `.dockerignore` | S | Security |
| 2 | Account lockout (per-email-hash) | M | Security |
| 3 | Backend Dockerfile non-root user | S | Security |
| 4 | Parameterise hardcoded compose credentials + add startup validator that asserts non-default secrets in production | M | Security / DevOps |
| 5 | Fix citations (`persist.py:42` → hydrate from `metadata_`) | XS | AI-Eng |
| 6 | Fix stage-name mismatch (`generate.py` → `"synthesizer"`; guardrail nodes use `"input_guard"`/`"output_guard"`) | XS | AI-Eng |
| 7 | Replace `check_clarification` regex with LLM call via `clarification_detector` resolver slot | S | AI-Eng |
| 8 | Postgres-backed LangGraph checkpointer | M | Architect |
| 9 | Tighten `chunks.embedder_id` NOT NULL + R3 migration completion | S | Architect |
| 10 | Unify repository session pattern; stop `Container.xxx_repo()` mid-request | M | Backend |
| 11 | Wire missing audit calls on `users.py` + `sources.py` (login, role change, source create/delete) | S | Security |
| 12 | Touch-target fix on chat citation buttons (`MessageThread.tsx:201`) | XS | UX |
| 13 | Add `connect-src $MINIO_PUBLIC_ENDPOINT` to CSP — currently breaks browser uploads in production | XS | Security |
| 14 | Handle Redis failure on rate limiter — fail-closed on `/api/v1/auth/login` (or warn-metric); current behaviour silently allows all | S | Security |

### Next (next month) — big levers

| # | Item | Effort | Owner area |
|---|---|---|---|
| 15 | Wire the missing pipeline nodes: `query_analyzer`, `source_router` (parallel retrievers), `text_to_query`, optional `reflector` | L | AI-Eng |
| 16 | Add reranker stage (Cohere `rerank-3.5` or BGE `bge-reranker-v2-m3` self-hosted) — top-30 → top-5 | M | AI-Eng |
| 17 | Hybrid retrieval (BM25 + vector RRF) — `tsvector` + GIN index, k=60 fusion | M | AI-Eng |
| 18 | Document-aware `ChunkStrategy` registry (PDF section-aware, Markdown headings, Excel row-groups, SQL row-as-doc) | M | AI-Eng |
| 19 | RAGAS-style eval harness with 50-question golden set, faithfulness ≥ 0.85 / context-precision ≥ 0.75 as ship gate | M | AI-Eng |
| 20 | Per-stage Langfuse attributes (model, tokens, USD cost) — already have `provider_model_metadata.py` price table | S | AI-Eng |
| 21 | Permission-based RBAC (`Permission` enum + `require_permission`) — keeps `require_admin` working as `require_permission(Permission.ANY_ADMIN)` | M | Architect |
| 22 | Structured logging with `trace_id`/`session_id` ContextVar propagation; ban f-strings in `logger.*` (ruff G004) | S | Backend |
| 23 | Consolidate `ProviderCatalog` Protocol — replace `provider_catalog` + `provider_model_metadata` + `STAGE_REQUIREMENTS` + `PROVIDER_FAMILY` drift | S | Architect |
| 24 | Move retrieval threshold (`SIMILARITY_THRESHOLD = 0.4`) and `top_k` (`= 10`) to admin-tunable `LLMConfiguration` rows | S | AI-Eng |
| 25 | Parallelise guardrail policy evaluation (`for policy in policies` → `asyncio.gather`) | S | AI-Eng |
| 26 | `PageHeader` + `StatusPill` + `DataTable` consolidation — eliminates 4 different page-header variants | M | UX |
| 27 | Cmd+K command palette (cmdk already a dep) + global shortcuts overlay | M | UX |
| 28 | Differentiate `/admin` (today / health) vs `/admin/analytics` (trends) — currently byte-for-byte identical; add first-run checklist on `/admin` | M | UX |
| 29 | Fernet `MultiFernet` key versioning + rotation procedure | L | Security |

### Later (this quarter) — quality / scale

| # | Item | Effort | Owner area |
|---|---|---|---|
| 30 | Reflector / corrective re-query loop (admin toggle, OFF by default per Constitution) | M | AI-Eng |
| 31 | Redis-backed semantic cache for repeated queries (PRD §6 names this) | S | AI-Eng |
| 32 | Query rewrite / decomposition for multi-hop questions | M | AI-Eng |
| 33 | CDC delta sync (Debezium) for SQL sources, replace timestamp polling | L | Architect |
| 34 | PgBouncer (transaction pooling) + connection-pool right-sizing | S | Backend |
| 35 | Celery queue partitioning (`ingest` for `sync_source`, `control` for tickers) + task-level idempotency keys | M | Backend |
| 36 | HNSW tuning (`m=32, ef_construction=200` for 1M+ vectors; per-query `ef_search`) | S | Backend |
| 37 | GIN index on `documents.metadata` and `chunks.metadata` JSONB | XS | Backend |
| 38 | Multi-tenant readiness: `tenant_id` columns + RLS in Postgres (no UI yet, just schema) | L | Architect |
| 39 | Secrets management: Vault / Docker secrets / SOPS for `JWT_SECRET`, `ENCRYPTION_KEY`, `OPENAI_API_KEY` | M | Security |
| 40 | Mobile card-list parity for AI Models / Embedders tables (port `SourceRowCard` pattern) | S | UX |
| 41 | Wizard-style refactor of `/admin/sources/new` (Type → Connection → Settings — currently 1250 LOC single-column) | M | UX |
| 42 | Onboarding: 4-step checklist on `/admin` for fresh installs ("Configure AI model → Add embedder → Connect first source → Invite team") | S | UX |

---

## Key per-team findings (skim if you need depth)

### Architecture (architect agent)
- **Strengths preserved:** AIModelResolver / EmbeddingServiceFactory pattern is exemplary. DTO separation + audit redaction is structural defense. Connector self-registration via decorator. pgvector cosine + typed bindparam are defense-in-depth. Constitution-as-code via Atomic Spec governance.
- **Top architectural debt:** pipeline lies (5 dead stages), `MemorySaver` non-durable, hand-coded `check_clarification` ignores its LLM, hard-coded `SIMILARITY_THRESHOLD`, fixed-size chunking, two repository session patterns, `Container.xxx_repo()` service locator anti-pattern, only 2-role RBAC.
- **References cited:** FastAPI advanced dependencies docs, LangGraph durable checkpointing docs, Anthropic Contextual Retrieval (Sept 2024), pgvector op-class match.

### AI / RAG pipeline (ai-engineer agent)
- **Pipeline reality vs claim:** 7 wired stages, 10 admin-configured slots, **5 dead slots**. `clarify` is regex. `source_router` / `text_to_query` / `reflector` not implemented. Generate.py uses wrong slot name → admin overrides never apply.
- **Production gaps (CRITICAL):** broken citations, no eval harness, N×LLM serial guardrails, no reranker, no hybrid search, single-cosine retrieval is the largest precision gap.
- **5 architecture-free quick wins:** fix citations (1 dict lookup), fix stage-name mismatch, lift Top-K + threshold to LLMConfiguration, parallelise guardrail policies via `asyncio.gather`, expose similarity scores in prompts so the LLM can refuse weak matches.
- **References cited:** Superlinked VectorHub on hybrid + reranking, premai 2026 production-RAG guide, BSWEN hybrid-vs-reranker comparison, roborhythms 2026 RAG pipeline guide.

### Backend code quality + scalability (backend-architect agent)
- **CRITICAL items:** repository session schism, `Container.xxx_repo()` mid-request leaks ungoverned sessions, `asyncio.run()` per Celery task creates fresh event loops (works only because prefork respawns).
- **HIGH items:** routers run raw queries that belong in repositories; `session.commit()` called twice per request in admin/ai_models.py creating partial-state windows; source-list N+1 hidden by lazy relationships; Pydantic v2 idiom inconsistency; `HTTPException` vs `AppError` schism; streaming partial-message persistence skipped on Exception.
- **Scalability ceilings at 10×:** DB pool exhaustion (currently 240 conns provisioned vs PG default 100 — needs PgBouncer), HNSW `m=16` recall floor at 1M+ vectors, Celery queue starvation, JSONB queries without GIN, MinIO single-bucket partition strategy.
- **References cited:** FastAPI SQL guide, FastAPI dependencies-with-yield, SQLAlchemy 2.0 async docs, pgvector indexing.

### UX / design system / accessibility (ui-ux-designer agent)
- **Coverage gaps:** no `Avatar`, `DropdownMenu`, `SegmentedControl`, `Breadcrumb`, `Pagination`, `Progress`, `Kbd`, `CopyButton`, `RelativeTime`, `StatusPill`. Recurring inline patterns waiting to be extracted.
- **Page audit:** `/admin/sources` is the gold standard. `/admin` and `/admin/analytics` are byte-for-byte duplicates (🔴). `/admin/sources/new` is a 1250-LOC single column begging for a wizard. Heading/CTA/empty-state patterns drift across 4 variants.
- **Accessibility (top issues):** chat citation buttons are 20×20 px (fails 44×44); KPI value updates not announced via `aria-live`; tables lack `<caption>`/`aria-label`; no skip-to-content; muted-foreground borderline at AAA in dark theme.
- **Top 5 next:** PageHeader/StatusPill/DataTable consolidation, mobile touch-target fix, Cmd+K palette, differentiate `/admin` vs `/admin/analytics` + first-run checklist, banner-vs-toast-vs-inline error policy.
- **References cited:** Linear (cmd+K + j/k row nav), Vercel templates (KPI hero + tabbed detail with deep-linkable `?tab=`), Mercury (sticky right-rail summary on long forms).

### Security posture (security-reviewer agent)
- **CRITICAL:** live OpenAI key in `backend/.env` on disk; hardcoded compose credentials with default fallbacks; no account lockout (per-IP only, 20/60s); backend containers run as root.
- **HIGH:** `__access` JWT readable by JS (architectural trade-off; needs CSP + tight TTL hardening); rate limiter silently degrades on Redis failure; audit log doesn't cover users / sources / login events; Fernet has no rotation path; CSP missing `connect-src` for MinIO.
- **OWASP Top 10 coverage:** Injection — covered. Cryptographic Failures — partial (no TLS enforcement on MinIO, no key rotation). Auth Failures — partial (no lockout, fragile rate limit). Logging & Monitoring — gap (audit incomplete). SSRF — partial (admin can point `base_url` at internal services).
- **Top 5 before production:** rotate key + `.dockerignore`, account lockout, non-root containers, `MultiFernet` key versioning, parameterise compose creds + startup security validator.
- **References cited:** OWASP Auth Cheat Sheet, OWASP Secrets Management Cheat Sheet, FastAPI security docs.

---

## Cross-cutting dependency graph

A handful of items unblock disproportionate downstream value:

```
[Stage-name fix #6] ──> admin overrides apply ──> Per-stage Langfuse attrs #20 ──> Cost dashboards
       │
       └────> Wire missing nodes #15 ──> Reranker #16 ──> RAGAS eval #19 ──> Production confidence
                       │
                       └────> Hybrid search #17 ──> Doc-aware chunking #18 ──> Recall on PDFs/code

[Repo session unify #10] ──> [PgBouncer #34] ──> 10× scale unblocked
       │
       └────> [LangGraph PostgresSaver #8] ──> Horizontal scaling unblocked

[Account lockout #2 + non-root #3 + rotate key #1] ──> Production sign-off threshold cleared
       │
       └────> [MultiFernet #29] ──> Customer-facing deployment threshold cleared
```

The single highest-leverage fix is **#6 stage-name mismatch + #15 wire missing nodes**. Everything else is downstream of the pipeline being honest about what it actually runs.

---

## What we are NOT doing (deliberate non-goals)

- **Multi-tenancy UI/business logic.** Schema-readiness only (item #38). Defer business logic until first multi-tenant customer.
- **OAuth / SSO.** Out of scope for v1; revisit when first enterprise customer asks.
- **Vertex AI / AWS Bedrock.** `openai-compatible` provider is the v1 escape hatch.
- **Anthropic embeddings.** Doesn't exist (Anthropic recommends Voyage).
- **Per-source heterogeneous embedders.** Single active embedder invariant for v1; revisit when corpus diversity demands it.

---

## Suggested next session

If we get one more focused round, do exactly these in order:
1. Fix #5 + #6 (citations + stage-name) — 30 minutes total, immediate user-visible quality jump
2. Fix #1 + #3 + #8 (rotate key, non-root containers, .dockerignore) — security baseline
3. Fix #10 (repo session unify) — unblocks PgBouncer + connection-pool tuning
4. Fix #2 + #11 (account lockout + audit on users/sources) — production security baseline
5. Wire #15 (missing pipeline nodes) — the flagship feature is finally honest

That sequence delivers a noticeably better product, a security-clean baseline, and a scalable repo-layer foundation in roughly one full day of focused work.

---

## File appendix

This document is a synthesis. The five underlying review reports are preserved verbatim in this conversation's transcript (commits authored 2026-04-25, branch `003-phase2-completion`). Key source files referenced across reviews:

- `backend/src/agent/pipeline.py`, `agent/nodes/{retrieve,generate,clarify,guardrail,history,persist}.py`, `agent/stage_defaults.py`, `agent/stage_requirements.py`
- `backend/src/services/{ai_model_resolver,embedding_service_factory,embedding_service,llm_config_service,guardrail_service,chunking_service,provider_catalog,provider_model_metadata,audit_service,storage_service,source_service,startup_seed}.py`
- `backend/src/repositories/{base_repository,chunk_repository,sync_job_repository,ai_model_repository,embedder_repository}.py`
- `backend/src/api/v1/{chat,sources,users}.py`, `api/v1/admin/{ai_models,embedders,llm_settings,policy}.py`
- `backend/src/core/{config,container,deps,crypto,database,exceptions}.py`
- `backend/src/middleware/{rate_limit,security_headers,error_handler,logging_middleware}.py`
- `backend/src/tasks/{sync_source,check_scheduled_syncs,trigger_all_syncs}.py`
- `backend/src/models/{base,chunk,source,user,ai_model,embedder,admin_audit_log,llm_configuration}.py`
- `backend/alembic/versions/{0007,0023,0024}_*.py`
- `frontend/src/components/{dashboard,chat,admin}/*`, `components/ui/*`
- `frontend/src/app/(admin)/admin/{sources,users,connectors,llm-settings,policy,ai-models,embedders,analytics}/*`
- `frontend/src/{lib/api-client.ts, features/auth/context/AuthContext.tsx, middleware.ts}`
- `docker-compose.yml`, `docker-compose.override.yml`, `.env.example`
- `docs/ai-models-and-embedders-design.md`, `docs/PRD.md`, `memory/constitution.md`
