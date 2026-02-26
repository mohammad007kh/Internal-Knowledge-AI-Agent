# T-079 — Phase 4 LangGraph Sign-Off

## Context
```
Phase 4 deliverables: T-070–T-078
Docker Compose 9 services
GitHub Actions CI
coverage ≥ 80% on app/agent/** and app/api/v1/chat.py
All FR-020–FR-026 acceptance criteria
LangGraph 8-node pipeline · interrupt() for clarification · SSE streaming
Langfuse traces visible in self-hosted Langfuse UI
```

## Goal
Final acceptance checklist for **Phase 4 — LangGraph RAG Pipeline & Chat**.  
All items must be ✅ before work on Phase 5 (Chat UI) begins.

---

## Deliverables Created in Phase 4

| Task | Deliverable |
|---|---|
| T-070 | `AgentState`, `ChatSession`/`ChatMessage` ORM, migration `0009`, pipeline scaffold |
| T-071 | `retrieve_context` node — pgvector HNSW search, FR-019 source filter |
| T-072 | `generate_response` node — OpenAI gpt-4o-mini, tenacity retry, Langfuse span |
| T-073 | `check_clarification` + `handle_clarification` — heuristic + `interrupt()` |
| T-074 | Full pipeline wiring — `MemorySaver`, `run_pipeline()`, DI `pipeline` Factory |
| T-075 | `LangfuseTracingService`, `ChatStreamEvent` SSE schema |
| T-076 | Chat API router — 5 endpoints, SSE streaming with `astream_events()` |
| T-077 | `ChatSessionService`, FR-019 source resolution, migration `0010` |
| T-078 | Integration tests — happy path, FR-019, clarification, session CRUD |

---

## 1  FR Acceptance Checklist

### FR-020 — Semantic search (retrieve_context)

- [ ] `retrieve_context` node returns chunks sorted by cosine distance (ascending)
- [ ] Only chunks from `state["source_ids"]` are returned (FR-019 enforced)
- [ ] Unit test passes with mocked embedding + chunk repo
- [ ] `HNSW` index on `chunks.embedding` verified via `EXPLAIN ANALYZE`

### FR-021 — LLM generation (generate_response)

- [ ] `generate_response` calls `gpt-4o-mini` with `temperature=0.2`, `max_tokens=1024`
- [ ] System prompt contains retrieved chunk texts
- [ ] On 3 consecutive OpenAI failures, node sets `state["error"]="generation_failed"`
- [ ] Token usage recorded in Langfuse span

### FR-022 — Clarification (check_clarification + handle_clarification)

- [ ] Query ≤ 5 chars sets `requires_clarification=True`
- [ ] `handle_clarification` calls `interrupt(question)` correctly
- [ ] `clarification` SSE event received by client from the API
- [ ] After user provides answer, pipeline resumes and routes to `retrieve_context`

### FR-023 — Conversation memory (load_history)

- [ ] `load_history` loads last 20 messages for the session
- [ ] Messages appear in `state["messages"]` as `HumanMessage` / `AIMessage`
- [ ] Session ownership validated (wrong user → empty history returned)

### FR-024 & FR-025 — Session CRUD

- [ ] `POST /chat/sessions` creates session, returns 201
- [ ] `GET /chat/sessions` returns paginated list sorted by `updated_at DESC`
- [ ] `DELETE /chat/sessions/{id}` soft-deletes (is_deleted=true)
- [ ] User cannot access another user's session (403 RFC 7807)

### FR-026 — SSE streaming

- [ ] `POST /chat/sessions/{id}/messages` returns `Content-Type: text/event-stream`
- [ ] SSE stream contains `delta` events for partial tokens
- [ ] SSE stream ends with `done` event containing `session_id` + `trace_id`
- [ ] `clarification` SSE event delivered when `interrupt()` fires
- [ ] `error` SSE event delivered on unrecoverable pipeline failure

---

## 2  Database Checklist

- [ ] Migration `0009_chat.py` applies cleanly on fresh DB
- [ ] Migration `0010_chat_source_ids.py` applies cleanly after 0009
- [ ] `chat_sessions.user_id` FK to `users.id` with `ON DELETE CASCADE`
- [ ] `chat_messages.session_id` FK to `chat_sessions.id` with `ON DELETE CASCADE`
- [ ] `messagerole` ENUM type created by migration
- [ ] `alembic downgrade -1` works for both migrations

---

## 3  LangGraph Pipeline Checklist

- [ ] `build_pipeline()` compiles without error
- [ ] `MemorySaver` checkpointer attached
- [ ] 8 nodes all registered: `load_history`, `check_clarification`, `handle_clarification`, `retrieve_context`, `generate_response`, `format_response`, `save_message`
- [ ] Conditional edge from `check_clarification` routes correctly
- [ ] `run_pipeline()` returns `final_answer` in integration smoke test

---

## 4  Langfuse Checklist

- [ ] Every pipeline run creates one trace in Langfuse (`chat_pipeline`)
- [ ] Trace has spans: `retrieve_context`, `generate_response`, `check_clarification`
- [ ] Trace `output` field contains the final answer (truncated to 1000 chars)
- [ ] `flush()` called at end of every run (no data loss on process restart)
- [ ] Langfuse UI accessible at `http://localhost:3010` in Docker Compose

---

## 5  FR-019 Security Enforcement Checklist

- [ ] `retrieve_context` with empty `source_ids` returns `[]` immediately
- [ ] `ChatSessionService.get_source_ids_for_session()` never returns unpermitted IDs
- [ ] `test_fr019_empty_source_ids_no_leak` passes
- [ ] Manual audit: confirmed no SQL query runs when `source_ids=[]`

---

## 6  Test Coverage Checklist

- [ ] `pytest --cov=app/agent --cov-fail-under=80` passes
- [ ] `pytest --cov=app/api/v1/chat --cov-fail-under=80` passes
- [ ] All node unit tests pass: `test_retrieve_node.py`, `test_generate_node.py`, `test_clarify_node.py`
- [ ] Integration smoke test passes: `test_pipeline_smoke.py`
- [ ] Chat API integration tests pass: `test_chat_sessions_api.py`, `test_chat_pipeline.py`

---

## 7  CI / Docker Checklist

- [ ] `docker-compose up --build` starts all 9 services without errors
- [ ] `make test-integration` runs Phase 4 tests in CI
- [ ] GitHub Actions `ci.yml` green on branch `feature/phase-4`
- [ ] `make migrate` applies migrations 0009 + 0010 in order

---

## 8  Definition of Done

Phase 4 is **complete** when:

1. All FR-020–FR-026 checkboxes are ✅  
2. CI green  
3. Langfuse traces visible for a manually triggered query  
4. No source-permission leaks found in FR-019 audit  
5. Signed off by a second reviewer  

**Next phase:** T-080 — Chat UI (Next.js streaming frontend)
