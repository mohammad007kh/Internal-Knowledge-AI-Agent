# How the Agentic System Works

**Last updated:** 2026-05-04
**Status:** Code-grounded reference. Every claim cites a file:line so you can verify.

This doc answers: *when a user types a message in the chat, what actually happens?*

---

## The 30-second version

1. Frontend `POST`s the message to `/api/v1/chat/sessions/{id}/messages` (SSE stream).
2. Backend looks up the session, the user's accessible **sources**, and kicks off the LangGraph pipeline.
3. The pipeline runs through up to 10 nodes (input guard → clarify → query analyze → source route → retrieve **or** text-to-SQL → synthesize → output guard → persist).
4. Each LLM-using node resolves its model via `AIModelResolver.resolve("<slot_name>")`, looking at the admin's per-stage config in the `llm_configurations` table.
5. The synthesizer streams tokens back to the client via SSE; citations come from chunk metadata.

The agent is **not** "one big model that sees everything." It's a graph of small specialized LLM calls, each configurable independently from `/admin/llm-settings`.

---

## The pipeline graph

Built in `backend/src/agent/pipeline.py`. Two versions exist; v2 is the default since Slice E.

### v2 (default — `PIPELINE_V2_ENABLED=True`)

```
START
  ↓
load_history          (reads recent messages from DB for context)
  ↓
guardrail_input       (LLM check: does this message violate policy?)
  ↓
check_clarification   (LLM check: is the question ambiguous? if yes → ask back)
  ↓
query_analyzer        (LLM rewrite: 1–3 search-friendly variants of the question)
  ↓
source_router         (LLM pick: which of the user's accessible sources should answer this?)
  ↓                    branches:
  ├── retrieve_context   (pgvector cosine search against indexed chunks)
  └── text_to_query      (only for sources of type `database` — generates a SELECT)
  ↓
generate_response     (synthesizer — the LLM that actually writes the answer using retrieved context)
  ↓
[reflector?]          (optional self-critic — OFF by default per Constitution)
  ↓
format_response       (assembles citations + final shape)
  ↓
guardrail_output      (LLM check on the answer before sending)
  ↓
persist               (saves the conversation turn to DB)
  ↓
END
```

Source files: every node lives under `backend/src/agent/nodes/`. Find a node by its name in `pipeline.py:_build_v2_pipeline`.

### v1 (legacy fallback — `PIPELINE_V2_ENABLED=False`)

```
load_history → check_clarification(heuristic, NOT LLM) → guardrail_input
  → retrieve_context → generate_response → format_response → guardrail_output → END
```

The v1 path exists as a 30-second rollback if v2 misbehaves in production. Same compiled graph signature, callers don't care which is active.

---

## The 10 admin-configurable stages

Every LLM-using node looks up its config from `llm_configurations` keyed by `slot_name`. Admins edit these at `/admin/llm-settings`. The 10 slots:

| Slot name | Wired? | Where it runs | What it does |
|---|---|---|---|
| `input_guard` | ✅ | `nodes/guardrail.py` (input branch) | Policy check on the user's message |
| `clarification_detector` | ✅ | `nodes/clarify.py:_llm_decision` | Decides if the question needs clarification |
| `query_analyzer` | ✅ | `nodes/query_analyzer.py` | Rewrites query into search variants |
| `source_router` | ✅ | `nodes/source_router.py` | Picks which sources to query |
| `text_to_query` | ✅ | `nodes/text_to_query.py` | Generates SQL for database sources |
| `synthesizer` | ✅ | `nodes/generate.py` (`_STAGE = "synthesizer"`) | The "main brain" — writes the answer |
| `output_guard` | ✅ | `nodes/guardrail.py` (output branch) | Policy check on the generated answer |
| `reflector` | ✅ (OFF by default) | `nodes/reflector.py` | Self-critic; can trigger one retry |
| `retrieval` | 🟡 not LLM | `nodes/retrieve.py` (uses embedder, not LLM) | Vector search; slot exists but isn't currently consulted |
| `schema_inspector` | 🟡 reserved | n/a | Reserved for future schema-introspection feature |

Eight of the ten slots are honest LLM calls today. The two yellow rows are stage-name placeholders for features that haven't shipped yet.

---

## How sources work

### What the agent sees

When `source_router` runs, it gets a list of the user's accessible sources:

```
[
  {id, name, source_type, description},   # one entry per source they can read
  ...
]
```

Source types currently shipped end-to-end: `file_upload`, `database`. `web_url` ingests but the recursive crawl mode is rolled back (single-page only); `confluence` and `sharepoint` are stub classes (frontend doesn't even show them in the picker).

### What "available sources" means per query

Per chat session, the user picks which sources to scope the conversation to (the "All sources" dropdown above the chat input). That gets stored on `chat_sessions.source_ids`. The pipeline reads that list and only queries within it.

The `source_router` node then picks a *subset* — for a question like "summarize Q3 revenue," it might decide that only the financial-report PDFs and the analytics database matter, ignoring HR docs that the user technically has access to.

If `source_router` returns nothing or errors, the pipeline falls back to "use ALL accessible sources" — never blocks the answer. (`source_router.py`)

### How retrieval actually finds chunks

`retrieve_context` (`nodes/retrieve.py`) does:

1. Get the active **embedder** from `embedders` table (`is_active=true` — partial unique index ensures exactly one active embedder per deployment in v1).
2. Embed the user's query (and the variants from `query_analyzer`) into a 1536-dim vector via the embedder's API.
3. Cosine similarity search in pgvector against the `chunks` table, filtered by `source_id IN (selected_sources)` and `embedder_id = active_embedder.id`.
4. Returns top-K chunks with `{chunk_id, source_id, text, score, document_title?, page_number?, source_name?}`.

Steps 4's metadata projection was added recently — the previous version dropped those keys, which is why citations used to render as raw UUIDs.

### How `text_to_query` is different

For sources of type `database`, the router can pick the `text_to_query` branch instead of vector retrieve. That node:

1. Resolves the source's stored connection config (decrypted Fernet ciphertext from `sources.config_encrypted`).
2. Sends the user's question + a schema sketch (today: the source's `description` field) to the LLM in slot `text_to_query`.
3. Validates the generated SQL with `is_safe_sql()` — must be a single `SELECT`, no semicolons, no `INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE/EXEC`, no `--` comments.
4. Wraps the SQL: `SELECT * FROM ({user_sql}) AS _q LIMIT 100` — prevents runaway queries.
5. Executes against the source's database, returns rows as "chunks" (with score=0.0, since vector ranking doesn't apply).

This branch is read-only by design **at the SQL safety layer**. Real `SET TRANSACTION READ ONLY` enforcement on the connection is on the roadmap (see "honesty notes" below).

---

## How the LLM enters the conversation

`generate_response` (`nodes/generate.py`):

1. `client = await ai_model_resolver.resolve("synthesizer")` — picks up the admin's configured model (provider, model_id, temperature, max_tokens, custom_prompt) from `llm_configurations` joined with `ai_models`.
2. Builds a prompt: system message (synthesizer prompt template, optionally overridden via admin custom_prompt) + recent conversation history + retrieved chunks (formatted with citation indices) + the user's current message.
3. Streams tokens via `client.chat.completions.create(stream=True)` — the streamed tokens flow back to the frontend as SSE events.
4. The final assembled answer (with citation references like `[1]` `[2]`) goes to `format_response` for citation hydration before the SSE close.

The admin can swap the underlying model per-stage at `/admin/llm-settings`. Set `synthesizer` to `gpt-4o`, `query_analyzer` to a cheaper `gpt-4o-mini`, `output_guard` to a hardened model — independent knobs.

---

## Embedder vs LLM — a common confusion

These are two different components:

- **LLM** (large language model): generates text. Lives in `ai_models` table. Examples: GPT-4o, Claude Sonnet, Gemini 2.5.
- **Embedder**: turns text into a fixed-length vector (a "fingerprint"). Lives in `embedders` table. Examples: `text-embedding-3-small` (1536 dims), `voyage-3-large` (1024 dims).

The embedder is used at **two** points: (1) when a source is synced (every chunk is embedded and stored), (2) when a query runs (the question is embedded so it can be compared to chunk vectors).

**Critical invariant:** chunks indexed with embedder X must be queried with embedder X. Cross-model embedding spaces are not aligned — using the wrong embedder returns near-random results without any error. v1 enforces "exactly one active embedder per deployment" via partial unique index. Switching embedders requires a re-index.

LLMs and embedders are *independent* axes. You can use Anthropic LLMs with Voyage embedders (Anthropic doesn't ship its own embeddings). The UI shows a soft hint when you mix providers but doesn't block you.

---

## Honesty notes (what the UI promises vs what's wired today)

A review pass called out a recurring "contract drift" bug class: UI fields collected from admins that the backend silently ignored. Three such items have been **rolled back** until the backend ships:

- ❌ "Force read-only credentials" checkbox — removed from UI. Real safety is the `is_safe_sql()` check in `text_to_query`. Re-enable when `SqlDatabaseConnector` applies `SET TRANSACTION READ ONLY` on connect.
- ❌ Recursive crawl for Web URL sources — removed from UI. Connector reads only `config["url"]` (single page). Re-enable when BFS + dedup + per-domain rate limit + page cap is implemented.
- ❌ "Schema inference" mode for blank SQL queries — reverted to required. The connector raises on blank query. Re-enable when `INFORMATION_SCHEMA` introspection is wired.

A new SSRF guard was added to `web_url_connector.py` so a malicious admin can't point a Web URL source at AWS metadata (`169.254.169.254`) or any RFC1918 / loopback / link-local address. 35/35 SSRF tests pass.

---

## What's NOT shipped (deferred)

- **Per-source heterogeneous embedders.** v1 enforces single-active. v1.1 plan: `chunks.embedder_id` becomes routable per query, multiple dim columns.
- **`MemorySaver` → `PostgresSaver`** for LangGraph durable checkpointing. Today, in-flight clarifications drop on restart.
- **Reranker stage** (Cohere or BGE). Today retrieval is single-cosine top-K; precision suffers at long-tail queries.
- **Hybrid retrieval** (BM25 + vector RRF). Same precision concern.
- **RAGAS evaluation harness.** No automated quality gate. Changes ship on visual sanity testing.

---

## Where to start reading the code

If you want to trace a single chat message through the system:

1. `frontend/src/components/chat/useChat.ts` — `send()` posts to the SSE endpoint
2. `backend/src/api/v1/chat.py` — the `send_message` route handler
3. `backend/src/agent/pipeline.py` — `build_pipeline()` returns the compiled graph
4. `backend/src/agent/nodes/` — one file per node, each ~100-200 lines
5. `backend/src/services/ai_model_resolver.py` — how each node gets its LLM
6. `backend/src/services/embedding_service_factory.py` — how the embedder is resolved
7. `backend/src/repositories/chunk_repository.py` — the actual pgvector cosine query

Every node is small, single-purpose, and individually testable. The whole pipeline is ~1500 lines of code.
