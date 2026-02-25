# Product Requirements Document
## Internal Knowledge AI Agent

> **Status:** In Progress — Living Document  
> **Last Updated:** 2026-02-25  
> **Version:** 0.6 (Decisions Resolved)

---

## Table of Contents

1. [Vision & Problem Statement](#1-vision--problem-statement)
2. [Target Users & Roles](#2-target-users--roles)
3. [Core Features](#3-core-features)
4. [System Architecture](#4-system-architecture)
5. [Tech Stack](#5-tech-stack)
6. [Key Design Decisions](#6-key-design-decisions)
7. [Data Sources & Connectors](#7-data-sources--connectors)
8. [Agentic RAG Pipeline](#8-agentic-rag-pipeline)
9. [Multi-LLM Configuration](#9-multi-llm-configuration)
10. [Context-Aware Chunking & Ingestion](#10-context-aware-chunking--ingestion)
11. [Access Control](#11-access-control)
12. [Source Sync & Re-ingestion](#12-source-sync--re-ingestion)
13. [Chat & Memory](#13-chat--memory)
14. [Admin Panel](#14-admin-panel)
15. [Observability](#15-observability)
16. [Deployment Model](#16-deployment-model)
17. [Data Models (High-Level)](#17-data-models-high-level)
18. [Authentication & Authorization](#18-authentication--authorization)
19. [Agent Guardrails & Safety](#19-agent-guardrails--safety)
20. [Open Questions & Backlog](#20-open-questions--backlog)

---

## 1. Vision & Problem Statement

### Vision

Companies accumulate knowledge in dozens of isolated silos — internal databases, PDFs, Word documents, spreadsheets, wikis. Finding the right information requires knowing *where* to look, having the right access, and manually synthesizing across sources.

This product gives every employee a single AI-powered conversational interface to their company's entire internal knowledge base. An intelligent agent automatically decides which sources to consult, retrieves the right context, and synthesizes a grounded answer — all while ensuring each user only sees what they're permitted to see.

### Problem

| Problem | Impact |
|---|---|
| Knowledge is siloed across DBs, files, and formats | Time wasted searching; decisions made on incomplete info |
| Non-technical users can't query databases | Dependency on engineering/analytics for basic data lookups |
| Document search is keyword-based, not semantic | Poor relevance; missed connections across documents |
| Connecting to a new data source is a developer task | Slow onboarding of new knowledge into the organization |

### Core Value Proposition

- **Single chat interface** across all company knowledge sources
- **AI-driven source routing** — no need to know where data lives
- **Admin-controlled sources** — no engineering changes needed to add/remove knowledge
- **Per-user access control** — RBAC at the source level
- **Fully self-hosted** — company data never leaves their infrastructure

---

## 2. Target Users & Roles

### Bootstrap: First Admin Account

The system cannot be used until at least one admin account exists. On **first startup**, the system detects zero users in the DB and enters **bootstrap mode**:
1. A `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD` environment variable pair is required in `.env`
2. On startup, if no users exist, the backend seeds the first admin account with these credentials (hashed) and immediately clears the env vars from runtime memory
3. The admin logs in with these credentials, is forced to change their password on first login
4. All subsequent users are invited by an admin

> **Alternative (deferred):** A one-time setup wizard UI on first visit. Simpler for non-technical admins, but requires an unauthenticated endpoint that must be locked after first use. Defer to V1. Each client company runs their own isolated Docker instance. No multi-tenancy within a deployment instance. Companies retain full data sovereignty.

### Roles

#### Admin
- Full control over the system
- Add, configure, edit, remove data sources
- Manage users (create, deactivate, assign roles, assign source access)
- Configure LLM settings per pipeline stage
- Trigger manual re-sync of sources
- Configure auto-sync schedules per source
- View observability dashboard (Langfuse)
- Access all sources regardless of per-user restrictions

#### User
- Access the chat interface
- Can only query sources they have been granted access to
- Persistent chat history (per user)
- Cannot modify sources or system settings

> **Note:** Future roles (e.g., Power User, Read-Only Admin) are deferred to backlog.

---

## 3. Core Features

### Must Have (MVP)

- [ ] **Multi-source connectors** — PostgreSQL, MS SQL, MongoDB, MySQL, PDF, Word (.docx), Excel (.xlsx), plain text, Markdown
- [ ] **Agentic RAG** — LangGraph-powered agent that intelligently routes queries to relevant sources
- [ ] **Context-aware chunking** — Source-type and model-aware document splitting and embedding
- [ ] **Schema auto-inspection** — On DB registration, AI analyzes tables/columns/samples and generates a natural language description for the admin to review/edit
- [ ] **Description auto-refresh** — Admin can trigger AI re-inspection of a registered source; AI diffs the new schema/content against the current description and proposes an updated one for approval
- [ ] **Admin panel** — Source management, user management, LLM configuration, sync settings
- [ ] **Per-user source access control** — Admins assign which sources each user can query
- [ ] **Persistent chat history** — All conversations stored per user in PostgreSQL
- [ ] **Streaming responses** — Token-by-token SSE streaming in the chat UI
- [ ] **Multi-LLM configuration** — Different LLM per pipeline stage, configurable by admin
- [ ] **Source sync options** — Manual trigger, scheduled auto-sync, or delta (incremental) sync per source
- [ ] **Per-source citation toggle** — Admin enables/disables source citation display per source; users can further toggle it on/off for themselves (within admin permission)
- [ ] **File upload storage via MinIO** — Uploaded documents stored in self-hosted MinIO (S3-compatible); no local filesystem dependency
- [ ] **IoC / Dependency Injection** — All services and repositories depend on abstractions (interfaces/protocols), resolved via a DI container; swapping DB or LLM provider requires no spaghetti changes
- [ ] **Agent clarifying questions** — When a user's query is ambiguous, the agent pauses and asks targeted clarifying questions before proceeding; implemented via LangGraph `interrupt()` with persistent state
- [ ] **Live source (Text-to-Query) retrieval** — DB sources support direct query generation and execution for both SQL (PostgreSQL, MS SQL, MySQL) and NoSQL (MongoDB MQL); enables precise analytical answers from live data
- [ ] **Source mode distinction** — Sources are tagged as `live` (DBs — queryable in real time) or `snapshot` (files — reflect last ingestion); freshness indicators shown in UI
- [ ] **Agent guardrails** — Input and output guard nodes wrap the entire agent pipeline; company-wide rules configured by admin; jailbreak prevention; sensitive data leak prevention
- [ ] **Source address security** — Connection strings, file storage paths, and internal IDs are structurally excluded from all API responses and LLM context; enforced via separate public/internal Pydantic DTOs
- [ ] **Observability** — Langfuse self-hosted for LLM tracing, token usage, latency

### Nice to Have (Post-MVP)

- [ ] Slack / Teams integration for chat
- [ ] Answer feedback (thumbs up/down) with logging
- [ ] Conversation summarization for long sessions
- [ ] API key management (for programmatic access)
- [ ] Audit log for admin actions

---

## 4. System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Client Layer                         │
│         Next.js + React + shadcn/ui (Admin + Chat UI)       │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST (CRUD) + SSE (streaming)
┌──────────────────────────▼──────────────────────────────────┐
│                       API Layer                             │
│                FastAPI (Python, async)                      │
│          Auth Middleware (JWT + RBAC)                       │
│          SSE Endpoints for streaming                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
┌─────────▼──────┐ ┌───────▼──────┐ ┌──────▼──────────┐
│  Agent Service │ │Source Service│ │   Auth Service  │
│  (LangGraph)   │ │  (Connectors)│ │  (Users/RBAC)   │
└─────────┬──────┘ └───────┬──────┘ └──────┬──────────┘
          │                │               │
┌─────────▼────────────────▼───────────────▼──────────┐
│                  Repository Layer                    │
│         (Data access — PostgreSQL + pgvector)        │
└─────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│                 Infrastructure Layer                 │
│   PostgreSQL + pgvector │ Redis │ External Sources  │
│   (app data, vectors,   │(Celery│(DBs, files, APIs) │
│    chat history)        │broker)│                   │
└─────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────┐
│              Background Worker (Celery)              │
│  Document ingestion, chunking, embedding, schema     │
│  inspection, scheduled re-sync                       │
└─────────────────────────────────────────────────────┘
```

### Architecture Pattern

**Layered Clean Architecture** within a **modular monolith**, with full **IoC / Dependency Injection**:
- `api/` — FastAPI routers, request/response models, auth middleware
- `services/` — Business logic, LangGraph agent, connector orchestration
- `repositories/` — Data access (SQLAlchemy + pgvector queries)
- `workers/` — Celery tasks (ingestion, sync, schema inspection)
- `connectors/` — Source-specific adapters (one per source type)
- `core/` — Config, **DI container**, interfaces/protocols, shared utilities

### Dependency Injection & IoC

The system uses an **IoC container** (`dependency-injector` library for Python) to wire all dependencies. Every service depends on an **abstract interface (Protocol)**, never on a concrete implementation.

```
IVectorRepository   ← PostgresVectorRepository  (or QdrantVectorRepository in future)
IDocumentRepository ← PostgresDocumentRepository
IFileStorage        ← MinIOFileStorage           (or LocalFileStorage for testing)
ILLMProvider        ← OpenAIProvider / AnthropicProvider / OllamaProvider
IConnector          ← PostgresConnector / MongoConnector / PDFConnector / ...
```

**Benefits:**
- Swapping the database = implement a new `IVectorRepository`, update the container binding. No other code changes.
- Swapping the file storage = implement `IFileStorage`. One line in the container.
- Every component is independently unit-testable with mock implementations.
- LLM providers are injected — not imported directly anywhere in business logic.

The DI container is configured at application startup from environment/database config and injects dependencies through FastAPI's `Depends()` mechanism.

### Frontend ↔ Backend Communication

| Operation | Protocol | Notes |
|---|---|---|
| All CRUD (sources, users, settings) | REST/JSON | Standard FastAPI endpoints |
| Chat message send | REST POST | Initiates a streaming response |
| Chat response stream | **SSE** | Token-by-token via `text/event-stream` |
| Auth | JWT (Bearer token) | Stored in httpOnly cookie |

---

## 5. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| **AI / Agent Framework** | LangChain + LangGraph | Agent orchestration, LLM abstraction, RAG chains |
| **Backend** | Python 3.12 + FastAPI | Async, native LangChain, SSE, clean DX |
| **Frontend** | Next.js 15 (App Router) + React + shadcn/ui | Chat + Admin panel, server components, great UI primitives |
| **App Database** | PostgreSQL 16 + pgvector | App data, chat history, vector embeddings — single service |
| **File Storage** | MinIO (self-hosted) | S3-compatible object store for uploaded documents; cloud-portable |
| **Background Jobs** | Celery + Redis | Async document ingestion, schema inspection, scheduled sync |
| **Caching / Broker** | Redis | Celery message broker + optional LangChain semantic cache |
| **Auth** | FastAPI + JWT + RBAC | Simple, stateless, well-understood |
| **DI / IoC** | `dependency-injector` (Python) | Interface-driven wiring; swap DB/LLM/storage without code changes |
| **Observability** | Langfuse (self-hosted) | LLM tracing, token cost, latency — no data leaves deployment |
| **Containerization** | Docker + Docker Compose | Full local stack, cloud-portable |
| **LLM Provider (default)** | OpenAI | Swappable via LangChain `BaseChatModel` abstraction |

---

## 6. Key Design Decisions

### Pipeline Latency & Cost Acknowledgment

The full pipeline (Input Guard → Clarification Detector → Query Analyzer → Source Router → N Retrievers → Synthesizer → Reflection → Output Guard) can trigger **6–10+ LLM calls** per user query. At GPT-4o pricing this is approximately **$0.10–$0.50+ per query** with **15–40s wall-clock latency** on a typical query.

**Mitigations built into the design:**
- Guard nodes use GPT-4o-mini (fast, cheap)
- Reflection Node is **opt-in** — disabled by default, enabled per deployment if quality warrants it
- LangChain semantic cache on Redis can short-circuit repeated near-identical queries
- Per-source LLM overrides allow cheaper models for low-stakes retrieval

**Acknowledged trade-off:** This is an enterprise internal knowledge tool, not a consumer product. Latency tolerance is higher than consumer chat. Cost is per-deployment, not per-user-seat. Still, this must be communicated to customers at sales/setup time.

Every component that calls an LLM receives a `BaseChatModel` instance resolved from configuration — not a hardcoded provider. The admin can configure a different LLM for each pipeline stage (see Section 9). Swapping providers requires only a config change, not a code change.

### Single-Tenant Per Deployment

Each company runs a fully isolated instance. No shared infrastructure between clients. This is the core data sovereignty guarantee of the product.

### PostgreSQL as the Single Persistence Layer

Rather than running a separate vector database, we colocate structured app data and vector embeddings in PostgreSQL using the `pgvector` extension. This reduces operational complexity for self-hosted deployments while providing sufficient performance for typical enterprise scale.

> **Revisit at scale:** If embedding search becomes a bottleneck (tens of millions of vectors), migrate vector storage to Qdrant while keeping app data in PostgreSQL. The repository abstraction makes this a contained change.

### pgvector Index Strategy

pgvector's default behavior is **exact scan (sequential O(n))**. For any production data volume, an HNSW index is required:
```sql
CREATE INDEX ON vector_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```
This must be created as part of the DB migration. `m` and `ef_construction` are tunable based on recall vs speed tradeoff. The repository layer must always query with a cosine or L2 operator that matches the index operator class.

Server-Sent Events are used for token streaming rather than WebSockets. Rationale: communication is unidirectional (server → client) for LLM streaming. SSE maps cleanly to LangChain's `.astream()`, is natively supported by FastAPI, and requires no connection upgrade handshake.

#### SSE Event Format (Citation-Aware)

Citation style is **inline footnotes** — the assistant response contains `[1]`, `[2]` references inline, with a collapsible references section below. The SSE stream must carry both the token stream and the citation payload.

```
# Token stream — one event per chunk
event: token
data: {"delta": "...text fragment [1]..."}

# Guardrail blocked the request (no tokens emitted)
event: guardrail_blocked
data: {"reason": "policy_violation", "message": "This query could not be answered per company policy."}

# Clarification needed (pipeline interrupted)
event: clarification_needed
data: {"question": "Did you mean the 2024 or 2025 sales figures?"}

# Final event — citation metadata for footnote rendering
event: citations
data: {
  "citations": [
    {"ref": 1, "source_name": "HR Policy", "doc_name": "leave_policy.pdf", "excerpt": "Employees are entitled to...", "page": 4},
    {"ref": 2, "source_name": "Finance DB", "doc_name": "budgets.xlsx", "excerpt": "Q3 total: ...", "page": null}
  ]
}

# Stream complete
event: done
data: {}
```

The `citations` event is only emitted if at least one cited source has `citations_enabled=true` and the user's citation preference is `show`. If citations are suppressed for all sources, the `citations` event is omitted; `[n]` markers are stripped from the token stream by the synthesizer prompt.

### Redis Role

Redis serves two purposes:
1. **Celery message broker** — required for background ingestion jobs
2. **LangChain semantic cache (optional)** — can cache LLM responses for near-identical queries, reducing cost and latency

### File Upload: Presigned URLs

Large file uploads (PDFs, Word, Excel) **must not** stream through the FastAPI backend — this causes memory exhaustion for multi-hundred-MB files. The correct pattern:
1. Frontend requests a presigned upload URL from the backend (`POST /sources/upload-url`)
2. Backend generates a MinIO presigned PUT URL (time-limited, scoped to a specific object key)
3. Frontend uploads the file **directly to MinIO** using the presigned URL — backend is bypassed for the actual bytes
4. Frontend notifies backend of completion; backend records `file_storage_path` and queues ingestion

This keeps the backend stateless with respect to file bytes and avoids memory pressure.
- No dependency on the local filesystem of any single container (safe to scale backend replicas)
- Easy migration to AWS S3 / Azure Blob later — same interface, one config change
- All file access goes through the `IFileStorage` abstraction; MinIO is just one implementation

---

## 7. Data Sources & Connectors

### Supported Source Types (MVP)

| Category | Sources |
|---|---|
| **Relational Databases** | PostgreSQL, MS SQL Server, MySQL |
| **NoSQL Databases** | MongoDB |
| **Documents** | PDF, Word (.docx), Plain Text (.txt), Markdown (.md) |
| **Spreadsheets** | Excel (.xlsx), CSV |

### Connector Architecture

Each source type has a dedicated **Connector** implementing a common interface:

```python
class BaseConnector(ABC):
    async def test_connection(self) -> bool
    async def inspect_schema(self) -> SourceSchema               # DB types
    async def load_documents(self) -> list[Document]             # file types
    async def load_delta(self, since: datetime) -> list[Document]

class LiveDBConnector(BaseConnector):
    async def execute_query(self, query: NativeQuery) -> QueryResult  # Text-to-Query path
    async def get_schema_context(self) -> str                         # schema for query generation
    async def validate_query_safety(self, query: NativeQuery) -> bool # block writes/drops

# NativeQuery is a union type:
#   SQLQuery(statement: str)              for relational DBs
#   MongoQuery(collection: str,           for MongoDB
#              operation: find | aggregate,
#              filter: dict,
#              pipeline: list | None)
```

### Source Mode: Live vs Snapshot

Sources are fundamentally split into two modes:

| Mode | Source Types | Retrieval | Freshness |
|---|---|---|---|
| **Live** | PostgreSQL, MS SQL, MySQL, MongoDB | Vector search AND/OR Text-to-Query (admin configures) | Always current when queried directly |
| **Snapshot** | PDF, Word, Excel, CSV, Markdown, Text | Vector search only | Reflects last ingestion timestamp |

#### Live Source Retrieval Modes (admin-configurable per DB source)

| Mode | When to use | How it works |
|---|---|---|
| `vector_only` | Source contains long-form text/descriptions | Standard pgvector similarity search over ingested rows |
| `text_to_query` | Source is structured/analytical data (sales, HR records, metrics) | LLM generates a native query → executed live → raw results fed to Synthesizer |
| `hybrid` | Source has both narrative and structured data | Router decides per query: semantic → vector; analytical → query; or both in parallel |

#### Text-to-Query: SQL vs NoSQL

**Relational DBs (PostgreSQL, MS SQL, MySQL):** Uses LangChain's `SQLDatabaseToolkit`. The LLM sees table/column descriptions from the approved source description + live `information_schema` context. Generates a `SELECT` statement. Executed via SQLAlchemy.

**MongoDB:** No direct LangChain toolkit equivalent — we build a custom `MongoQueryTool` on LangChain's `BaseTool` abstraction. The LLM sees: collection names, sample documents (3–5 docs per collection, sampled at registration), and field descriptions from the source description. The LLM generates a MongoDB operation as structured JSON:
```json
{ "collection": "orders", "operation": "aggregate",
  "pipeline": [{"$match": {"status": "shipped"}}, {"$group": {"_id": "$region", "total": {"$sum": "$amount"}}}] }
```
The connector deserializes this, validates safety, and executes via `pymongo`.

> **Safety (all DB types, enforced at connector level, not by the LLM):**
> - **SQL:** Only `SELECT` statements pass `validate_query_safety()`. Any `INSERT`, `UPDATE`, `DELETE`, `DROP`, `TRUNCATE`, `EXEC`, or semicolons indicating multiple statements → rejected.
> - **MongoDB:** Only `find` and `aggregate` operations allowed. `insertOne`, `updateMany`, `deleteMany`, `drop`, `$merge`, `$out` in pipelines → rejected.
> - The LLM output is parsed and validated before execution — it is never `eval()`'d or passed as raw string to the DB driver.

#### UI Freshness Indicators
- **Live sources** in `text_to_query` or `hybrid` mode: show a **"Live"** green badge — data is always current
- **Snapshot sources**: show **"Last updated: X days ago"** using `last_ingested_at`
- **Live sources** in `vector_only` mode: show last sync time (vectors may lag behind live DB)

### Source Registration Flow (Admin)

1. Admin selects source type and provides connection details (connection string, or file upload to MinIO)
2. System immediately runs **schema inspection** (for DBs) or **document preview** (for files)
3. AI generates a natural language description: *"This database contains employee records, department hierarchies, and payroll data..."*
4. Admin reviews, edits if needed, and approves the description
5. Admin configures:
   - Sync settings (manual / scheduled / delta — see Section 12)
   - **Citation visibility** — whether this source's name/location can be shown in answers (`citations_enabled: true | false`)
6. Source is saved; background ingestion job is queued (Celery)
7. Admin assigns user access permissions to this source

### Description Auto-Refresh (Admin)

At any time after registration, an admin can trigger **"Refresh Description"** on a source:
1. The system re-runs schema inspection (for DBs: re-reads tables, columns, samples; for files: re-parses structure)
2. The LLM compares the new schema/content snapshot against the **current saved description**
3. It produces a diff-aware updated description: *"Previously: employee records. Now also includes: new `projects` table tracking cross-department initiatives..."*
4. Admin reviews the proposed update and approves or dismisses it
5. Approved description replaces the old one; previous description is archived in `SourceDescriptionHistory`

### Source Metadata Stored Per Source

```
- id, name, type, description (admin-approved, AI-generated)
- connection_config (encrypted at rest)  ← DB sources
- file_storage_path                       ← file sources (MinIO object key)
- source_mode: live | snapshot
- retrieval_mode: vector_only | text_to_query | hybrid  ← live (DB) sources only
- embedding_model (which model to use for this source's vectors)
- chunk_strategy (source-type-aware chunking config)
- sync_mode: manual | scheduled | delta
- sync_schedule (cron expression, if scheduled)
- last_synced_at
- status: pending | ingesting | ready | error | stale | paused
- citations_enabled: bool  ← admin controls whether citations can be shown for this source
- created_by, created_at, updated_at

> **Note on LLM config per source:** Per-source LLM overrides (retrieval model, text-to-query model) are stored in a separate `SourceLLMConfig` table (see §17), not as JSONB blobs on `Source`. LLM stage configs in `LLMStageConfig` are system-level defaults; `SourceLLMConfig` rows override them per source.
```

---

## 8. Agentic RAG Pipeline

### LangGraph Agent Architecture

```
User Message + Chat History + User's Accessible Sources
        │
        ▼
┌───────────────────┐
│   Input Guard     │  Jailbreak detection, prompt injection scan
│   (LLM + rules)   │  Company rule compliance check
│                   │  If blocked → emit guardrail_blocked SSE event; stop
└────────┬──────────┘
         │  (query passed input guard)
         ▼
┌───────────────────┐
│  Clarification    │  Is the query clear enough to proceed?
│  Detector         │  If ambiguous → emit clarifying questions via SSE
│  (LLM call)       │  Graph pauses (interrupt()); resumes when user replies
└────────┬──────────┘
         │  (clear query, or clarification received)
         ▼
┌───────────────────┐
│  Query Analyzer   │  Extracts intent, entities, rephrases if needed
│  (LLM call)       │  Context-aware: uses chat history + any clarifications
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  Source Router    │  Decides which source(s) to query
│  (LLM call)       │  Uses source descriptions as routing metadata
│                   │  Only routes to sources the user can access
└────────┬──────────┘
         │ (may select multiple sources → parallel branches)
    ┌────┴──────────────┐
    │                   │
    ▼                   ▼
┌──────────────┐  ┌──────────────┐   (one branch per selected source)
│ Snapshot Src │  │  Live DB Src │
│  Retriever   │  │  Retriever   │
│ (vector      │  │ (vector OR   │
│  search)     │  │  text-to-SQL │
│              │  │  OR hybrid)  │
└──────┬───────┘  └──────┬───────┘
    └─────────┬─────────┘
              │
              ▼
┌───────────────────┐
│   Synthesizer     │  Merges, deduplicates, ranks retrieved context
│   (LLM call)      │  Generates the final grounded answer
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  Reflection Node  │  Optional: checks answer quality, completeness
│  (LLM call)       │  If insufficient → loop back to Router
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  Output Guard     │  Scan answer for leaked connection strings,
│  (LLM + regex)    │  file paths, internal IDs, credentials
│                   │  Company rule compliance on the answer
│                   │  If violation → sanitize or replace with safe refusal
└────────┬──────────┘
         │
         ▼
  Streamed Response (SSE)
```

### Clarifying Questions (Human-in-the-Loop)

When the **Clarification Detector** determines a query is too vague to answer reliably, it:
1. Generates 1–3 targeted clarifying questions (e.g. *"Are you asking about the current quarter or year-to-date?"* / *"Which department's policy are you referring to?"*)
2. The LangGraph graph **pauses** at this node using LangGraph's native `interrupt()` mechanism
3. Graph state (the full in-progress run) is **persisted** via LangGraph checkpointing (stored in PostgreSQL or Redis)
4. The SSE stream emits a special event instead of tokens:
   ```json
   { "type": "clarification_needed", "questions": ["...", "..."] }
   ```
5. The frontend renders these as a distinct question card UI component — not a regular message bubble
6. The user types their answer and submits via the normal chat input
7. The backend **resumes** the paused LangGraph run, injecting the user's answer as input to the interrupted node
8. Both the questions and the user's answer are stored as `ChatMessage` rows with `message_type: clarification_request` / `clarification_response`
9. The graph continues from where it paused — Query Analyzer now has a clear, enriched query

> This is implemented entirely within LangGraph's state machine — not a separate system. The `thread_id` (chat session ID) is used to resume the correct graph run.

### Context-Aware RAG

The agent is aware of conversational context at every step:
- **Clarification Detector** checks prior turns before deciding if more info is needed
- **Query Analyzer** uses the last N messages to resolve pronouns, carry context ("tell me more about *that*")
- **Chat history** is summarized if the session is long (to stay within context window)
- **Source Router** considers prior routing decisions in the session to maintain coherence
- **Synthesizer** includes relevant prior answers when building the final response

---

## 9. Multi-LLM Configuration

Each pipeline stage has an independently configurable LLM. Admins set these in system settings.

### Configurable LLM Slots

| Stage | Purpose | Default |
|---|---|---|
| `schema_inspector` | DB schema analysis + description generation | GPT-4o |
| `clarification_detector` | Determines if query is ambiguous; generates clarifying questions | GPT-4o-mini |
| `query_analyzer` | Intent extraction, query rewriting (post-clarification) | GPT-4o-mini |
| `source_router` | Deciding which source(s) to query and retrieval mode | GPT-4o |
| `retrieval` | Vector retrieval reasoning (default for all sources; overridden per source in `SourceLLMConfig`) | GPT-4o-mini |
| `text_to_query` | Query generation for live DB sources — SQL or MongoDB MQL (overridden per source in `SourceLLMConfig`) | GPT-4o |
| `synthesizer` | Final answer generation from all retrieved context | GPT-4o |
| `reflector` | Answer quality check; **disabled by default** — enable via `REFLECTION_ENABLED=true` env var or admin settings UI; triggers retry loop when enabled | GPT-4o-mini |
| `input_guard` | Jailbreak detection + company rule compliance on user input | GPT-4o-mini |
| `output_guard` | Sensitive data scan + company rule compliance on agent answer | GPT-4o-mini |

> **System-level vs per-source LLM config:** `LLMStageConfig` stores the system-level default per named stage. For `retrieval` and `text_to_query`, `SourceLLMConfig` rows can override the default for a specific source. No other stages support per-source overrides at MVP.

### LLM Config Schema (per slot)

```
- provider: openai | anthropic | ollama | azure_openai | google
- model: e.g. gpt-4o, claude-3-5-sonnet, llama3.2
- api_key (encrypted)
- base_url (for Ollama or Azure custom endpoints)
- temperature
- max_tokens
- context_window_tokens  ← used to guide chunking strategy
```

### Tokenization & Chunking Awareness

Chunking is **model-aware**:
- Each source's chunks are sized relative to the `context_window_tokens` of its assigned retrieval LLM
- Token counting uses the provider's tokenizer (tiktoken for OpenAI, provider-specific otherwise)
- LangChain's `RecursiveCharacterTextSplitter` with per-model token counters handles this
- If the retrieval LLM for a source changes, affected documents are flagged for re-chunking

---

## 10. Context-Aware Chunking & Ingestion

### Strategy Per Source Type

| Source Type | Chunking Strategy |
|---|---|
| **PDF** | Semantic chunking: respect section headers, page boundaries; extract metadata (page num, section title) |
| **Word (.docx)** | Respect heading hierarchy (H1/H2/H3); paragraphs as atomic units |
| **Markdown** | Split on heading boundaries; preserve code blocks as atomic units |
| **Plain Text** | Recursive character splitting with sentence-boundary awareness |
| **Excel / CSV** | Row-group chunking; preserve column headers in every chunk |
| **Database (SQL)** | Row-level documents; include table name + column names as context prefix in every chunk |
| **MongoDB** | Document-level chunking; nested field flattening with path-aware metadata |

### Metadata Attached to Every Chunk

Every vector stored in pgvector carries:
```
- source_id
- source_type
- chunk_index
- source-specific metadata (page, section, table name, row id, etc.)
- embedding_model (which model produced this vector)
- ingested_at
```

This metadata enables:
- **Filtered retrieval** — only query vectors from sources the user can access
- **Citation generation** — tell the user exactly which page/table/document the answer came from
- **Selective re-ingestion** — only re-embed chunks from changed rows/documents

---

## 11. Access Control

### Model

- Each **source** has an **access list** of user IDs that can query it
- Admins manage this list from the source management panel
- At query time, the **Source Router** receives only the list of sources accessible to the requesting user — it physically cannot route to unauthorized sources
- Vector search queries include a `source_id IN (user_accessible_source_ids)` filter

### Citation Visibility Control

Citation display is controlled at two levels:

1. **Admin level (per source):** The admin sets `citations_enabled` on each source at registration. If `false`, the source is never cited in answers — regardless of user preference. Useful for sensitive sources where even acknowledging *that* the answer came from them is undesirable.
2. **User level (preference):** If the admin has enabled citations for a source, each user can toggle *"Show source citations in answers"* in their own settings. Users cannot enable citations for sources where the admin has disabled them.

| Scenario | Admin `citations_enabled` | User preference | Citations shown? |
|---|---|---|---|
| Both enabled | ✅ | Show | ✅ Yes |
| Admin enabled, user hides | ✅ | Hide | ❌ No |
| Admin disabled | ❌ | Any | ❌ No |

### Role Summary

| Action | Admin | User |
|---|---|---|
| Chat with AI | ✅ (all sources) | ✅ (assigned sources only) |
| View own chat history | ✅ | ✅ |
| View all users' chat history | ✅ | ❌ |
| Add / edit / remove sources | ✅ | ❌ |
| Configure LLM settings | ✅ | ❌ |
| Manage users | ✅ | ❌ |
| Assign source access to users | ✅ | ❌ |
| Enable/disable citations per source | ✅ | ❌ |
| Toggle citation display in their own chat | ✅ | ✅ (if admin allowed) |
| Trigger manual re-sync | ✅ | ❌ |
| Refresh source description (AI) | ✅ | ❌ |
| View Langfuse observability | ✅ | ❌ |

---

## 18. Authentication & Authorization

### AuthN — Authentication (Who are you?)

Proves identity. Handles login, token issuance, and session lifecycle.

#### Flow
1. User submits `email` + `password` to `POST /auth/login`
2. Backend verifies `bcrypt` password hash against the DB
3. On success, issues two tokens:
   - **Access token** — JWT, signed with `JWT_SECRET`, 15-minute TTL. Payload: `{ user_id, email, role }`.
   - **Refresh token** — opaque random token, 7-day TTL. Stored hashed in DB (`RefreshToken` table). Sent in `httpOnly`, `Secure`, `SameSite=Strict` cookie only — never in JSON response body.
4. All subsequent API requests include `Authorization: Bearer <access_token>` header
5. When the access token expires, the client calls `POST /auth/refresh` — the httpOnly cookie is sent automatically, backend validates the refresh token, issues a new access token + rotates the refresh token
6. `POST /auth/logout` invalidates the refresh token in DB immediately

#### Token Security Rules
- Access tokens are short-lived (15 min) — even if intercepted, window of exposure is small
- Refresh tokens never appear in JavaScript-accessible storage
- Refresh token rotation: each use issues a new one and invalidates the old one (detects theft)
- Tokens contain only `user_id`, `email`, `role` — no source IDs, no sensitive data

---

### AuthZ — Authorization (What can you do?)

Enforced at **four independent layers**. All four must pass for any sensitive operation:

#### Layer 1 — Route-level RBAC
FastAPI dependency injection on every router:
```python
# Admin-only routes
@router.post("/sources", dependencies=[Depends(require_role("admin"))])

# Any authenticated user
@router.post("/chat", dependencies=[Depends(require_authenticated())])
```
Checked before any service or DB call. Returns `403 Forbidden` immediately if role insufficient.

#### Layer 2 — Resource-level source access
- All chat/query operations load `accessible_source_ids` from `SourceAccess` for the requesting user
- This list is injected into the LangGraph agent state at the start of every run
- The **Source Router node** only ever sees sources from this list — it cannot hallucinate access to others
- Text-to-Query: connectors are only instantiated for sources in this list
- Vector search: always executed with `WHERE source_id = ANY(:accessible_source_ids)` — enforced at the SQL level in the repository, not in service logic

#### Layer 3 — API response serialization (DTO separation)
Every entity has two Pydantic models:

| Model | Used where | Contains sensitive fields? |
|---|---|---|
| `SourceInternal` | Within backend services only | ✅ connection_config, file_storage_path, encryption keys |
| `SourcePublic` | All API responses | ❌ Never — only name, type, description, status, mode |

FastAPI's `response_model=SourcePublic` parameter enforces this at the framework level — **it is structurally impossible** for `connection_config` or `file_storage_path` to appear in a response even if a developer accidentally passes `SourceInternal` to the serializer.

This pattern applies to all sensitive models: `UserInternal` / `UserPublic`, `LLMStageConfigInternal` / `LLMStageConfigPublic`, etc.

#### Layer 4 — LLM context isolation
Sensitive fields never enter LLM context. Specifically:
- Connection strings are never included in any prompt, retrieval result, or agent state
- MinIO object keys (file paths) are never included in prompts or chunk metadata returned to the LLM
- Citation metadata shown to users contains only: source name, human-readable location (page number, table name, section heading) — never internal paths or IDs
- The Output Guard node additionally scans every LLM-generated answer for credential-like patterns (connection string patterns, `://` URLs with credentials, UUIDs matching internal IDs) before streaming begins

---

### Summary: What a User Can Never See

| Data | Why protected | How protected |
|---|---|---|
| Connection strings | Direct DB access | DTO separation; never in LLM context |
| MinIO file paths / object keys | Direct file access | DTO separation; never in chunk metadata |
| Other users' data | Privacy | SourceAccess filter on all queries |
| Source names/existence of unauthorized sources | Information leakage | Agent state only contains accessible sources |
| Internal IDs used for security decisions | Enumeration attacks | Public DTOs use opaque UUIDs only |
| API keys / LLM credentials | Provider account access | DTO separation; encrypted at rest |

---

## 19. Agent Guardrails & Safety

### Overview

Two dedicated **Guard Nodes** wrap the entire agent pipeline (see Section 8 diagram):
- **Input Guard** — runs before the agent processes the query
- **Output Guard** — runs after the Reflection Node, before streaming to the user

Both nodes are fast, cheap LLM calls (configured to use a small model by default, e.g. GPT-4o-mini) augmented by deterministic rule checks.

### Company Rules (Admin-Configured)

The admin configures **system-wide agent behavior rules** in the Admin Panel — a `CompanyPolicy` record in the DB. This is injected as a system prompt prefix into both Guard nodes:

```
Examples of company rules an admin might write:
- "Never discuss competitor products or make comparisons."
- "Always respond formally. Do not use casual language."
- "Do not reveal salary information to users outside the HR department."
- "Answers must be grounded in company data only. Do not use general knowledge."
- "Always recommend contacting IT support for technical issues."
```

Rules are plain natural language — no special syntax required. The admin writes them in a text area in the Admin Panel. They are versioned (each save creates a new `CompanyPolicyVersion` record).

### Input Guard — What it checks

| Check | Type | Action on fail |
|---|---|---|
| **Jailbreak / prompt injection** | LLM + pattern matching | Block; emit `guardrail_blocked` SSE event |
| **Prompt injection via uploaded content** | Regex scan on retrieved chunks before synthesis | Strip injection attempt; log |
| **Company rule violation** (e.g. asking about competitors) | LLM with rules injected | Block with a configured refusal message |
| **Out-of-scope query** (if admin enables strict mode) | LLM | Soft-redirect: *"I can only answer questions about [company] data"* |
| **Obvious PII extraction attempt** (bulk scrape) | Rule-based heuristics | Block |

Jailbreak pattern examples caught by pattern matching (before any LLM call):
- *"Ignore previous instructions"*, *"You are now..."*, *"DAN"*, *"pretend you have no restrictions"*
- Base64 encoded instructions in the message
- Unusually long messages with embedded system-prompt-like structure

### Output Guard — What it checks

| Check | Type | Action on fail |
|---|---|---|
| **Leaked connection string** | Regex (`://`, credential patterns) | Strip from answer; replace with `[REDACTED]`; log alert |
| **Leaked internal file path** | Regex + MinIO path patterns | Strip; log alert |
| **Leaked internal IDs / UUIDs that match sensitive records** | Lookup against known sensitive ID patterns | Strip |
| **Company rule violation in answer** | LLM | Replace answer with safe refusal |
| **Hallucinated source attribution** (LLM claims source doesn’t exist) | Cross-check cited sources against accessible list | Remove invalid citation |

Output Guard runs on the **complete assembled answer** before streaming begins. If a violation is detected:
1. Minor issues (leaked paths, invalid citations) → sanitized silently, logged
2. Policy violations → the answer is discarded and replaced with a generic refusal
3. All incidents are logged to a `GuardrailEvent` table for admin review

### Guardrail Blocked — User Experience

When the Input Guard blocks a query, the SSE stream emits:
```json
{ "type": "guardrail_blocked", "message": "I’m not able to help with that request." }
```
The frontend renders this as a distinct system message. The blocked query and reason are stored in `ChatMessage` with `message_type: guardrail_blocked` and in `GuardrailEvent` for audit purposes.

The refusal message text is configurable by the admin (e.g. *"Please contact your IT department for that type of request."*).

### What Guardrails Do NOT Do

- They do **not** replace proper AuthZ. A user who passes all guards still cannot access sources they don’t have permission to.
- They are **not** a firewall. Deep network-level security is the responsibility of the deployment environment.
- They do **not** guarantee 100% jailbreak prevention — no LLM-based guard can. They raise the bar significantly and log all attempts.

---

## 12. Source Sync & Re-ingestion

> **Terminology note:** Three related operations are kept distinct throughout this document:
> - **Sync** — fetching new/changed data from the external source
> - **Ingestion** — chunking, embedding, and storing vectors from that data  
> - **Re-index** — rebuilding the vector index after chunk changes
> "Re-sync" triggers ingestion which may trigger re-indexing. They are not interchangeable.

Each source has a **sync mode** configured at registration (editable later):

### Sync Modes

| Mode | Behavior |
|---|---|
| **Manual** | Admin clicks "Sync Now" in the admin panel. No automatic updates. |
| **Scheduled** | Admin sets a cron expression (e.g., every night at 2am). Celery Beat triggers re-ingestion on schedule. |
| **Delta (Incremental)** | System tracks the last sync timestamp. On each sync cycle, only content *added or modified after that timestamp* is re-indexed. Full re-sync is skipped entirely. |

> **What is delta sync?** "Delta" (Δ) is a standard data engineering term meaning *the change between two states*. Delta sync = sync only the diff, not the whole dataset. Used universally in ETL pipelines, database replication, and data warehousing.

### Delta Sync Details (MVP: polling-based)

For MVP, delta sync uses **timestamp polling** — simple, reliable, no extra infra:
- **SQL DBs:** Admin specifies which column to use as the change timestamp (e.g., `updated_at`, `modified_date`). System queries `WHERE updated_at > last_synced_at` on each cycle.
- **Files (MinIO):** MinIO object `LastModified` metadata + SHA-256 content hash comparison. If hash differs → re-ingest.
- **MongoDB:** Admin configures the timestamp field (e.g., `updatedAt`). Query: `{ updatedAt: { $gt: last_synced_at } }`.

> **Post-MVP:** Full CDC (Change Data Capture) via Debezium for SQL DBs — more accurate, captures deletes, but adds a container to the stack. Deferred.

### Re-index Behavior
When content changes are detected:
1. Old vectors for the changed document/row are deleted from pgvector
2. New chunks are generated and embedded
3. New vectors are inserted with updated `ingested_at` metadata

---

## 13. Chat & Memory

### Chat History
- All messages (user + assistant) stored in PostgreSQL per user
- Each conversation is a **Session** with a unique ID
- Sessions can be named/renamed by the user
- Users can view past sessions from the chat sidebar

### Memory Strategy
- **Within a session:** Full message history passed to Query Analyzer (summarized if exceeding context window)
- **Across sessions:** No automatic cross-session memory at MVP (backlog: long-term user memory via memory store)

### Streaming
- Assistant responses are streamed token-by-token via SSE
- The full response is persisted to PostgreSQL once the stream completes
- If the stream is interrupted, partial responses are flagged in the DB

---

## 14. Admin Panel

### Sections

#### Sources
- List all sources (status, last sync, type, description)
- Add new source (guided flow with schema inspection + citation toggle)
- Edit source (description, sync settings, LLM config override, citation toggle)
- **"Refresh Description"** button — triggers AI re-inspection, diffs vs current description, presents proposed update for admin approval
- Remove source (with confirmation + vector cleanup)
- Trigger manual sync
- View sync history / error logs per source

#### Users
- List all users
- Invite new user (email + role)
- Edit user (role, active/inactive)
- Manage source access per user (assign/revoke)
- View user's chat session list (admin oversight)

#### User Settings (self-service, in chat UI)
- Toggle: *"Show source citations in answers"* (only available if admin enabled citations on at least one accessible source)

#### LLM Settings
- Configure LLM per pipeline stage (see Section 9)
- Test LLM connection
- View token usage summary (pulled from Langfuse)

#### System Settings
- General settings (app name, logo, etc.)
- Sync schedules overview

#### Observability
- Embedded Langfuse dashboard or link to self-hosted Langfuse UI

---

## 15. Observability

**Tool:** Langfuse (self-hosted, part of Docker Compose stack)

### What's Traced
- Every LangGraph agent run (full trace of all nodes)
- LLM calls per stage: model, prompt tokens, completion tokens, latency, cost estimate
- Retrieval steps: which sources queried, number of chunks retrieved
- Errors and retries in the agent graph

### Integration
- LangChain `CallbackHandler` → `LangfuseCallbackHandler` attached to every chain/agent invocation
- Requires no changes to business logic — callbacks are injected at the service layer

---

## 16. Deployment Model

### Local Development

Full stack via **Docker Compose**:

```
services:
  - frontend       (Next.js)
  - backend        (FastAPI)
  - worker         (Celery workers — ingestion/query tasks)
  - beat           (Celery Beat scheduler — MUST be a single separate service; scaling worker replicas does NOT scale beat)
  - db             (PostgreSQL + pgvector)
  - redis          (Celery broker + cache)
  - minio          (self-hosted S3-compatible file storage)
  - langfuse       (self-hosted observability)
  - langfuse-db    (PostgreSQL for Langfuse — separate instance)
```

> **Critical:** `beat` and `worker` must never run in the same container replica when `worker` is scaled. Running two `beat` instances causes duplicate scheduled sync jobs. The Compose file must define `beat` as a separate service with `replicas: 1`.

### Production (Future)

Docker Compose remains valid for single-server deployments. For larger scale:
- Kubernetes (Helm chart) — TBD
- Each service is independently scalable (backend replicas, multiple workers)
- Environment-variable-driven config ensures no code changes between envs

### Environment Config

All secrets and env-specific values via `.env`:
- `DATABASE_URL`
- `REDIS_URL`
- `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`
- `OPENAI_API_KEY` (can be overridden per-stage in admin DB settings)
- `LANGFUSE_SECRET_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_HOST`
- `JWT_SECRET`
- `ENCRYPTION_KEY` (for encrypting stored connection strings / API keys)

---

## 17. Data Models (High-Level)

```
User
  - id, email, hashed_password, role (admin|user), is_active
  - show_citations_preference: bool  ← user-level citation toggle
  - created_at, updated_at

Source
  - id, name, type, description (admin-approved)
  - source_mode: live | snapshot
  - retrieval_mode: vector_only | text_to_query | hybrid  ← live sources only
  - connection_config (encrypted)   ← DB sources  [INTERNAL ONLY — never in API responses]
  - file_storage_path               ← file sources (MinIO object key) [INTERNAL ONLY]
  - embedding_model_id (FK EmbeddingModelConfig)
  - chunk_strategy_config
  - sync_mode: manual | scheduled | delta
  - sync_schedule (cron expression)
  - last_synced_at
  - status: pending | ingesting | ready | error | stale | paused
  - citations_enabled: bool         ← admin-level citation toggle
  - created_by (FK User), created_at, updated_at

SourceDescriptionHistory
  - id, source_id (FK Source)
  - description (previous text), replaced_at, replaced_by (FK User)

SourceAccess
  - source_id (FK Source), user_id (FK User)
  - granted_by (FK User), granted_at

Document  (logical unit from a source — a file, a DB table, etc.)
  - id, source_id (FK Source), external_id (file path, table name, row id)
  - content_hash, last_ingested_at

VectorChunk  (pgvector table)
  - id, document_id (FK Document), source_id (FK Source)
  - content (text), embedding (vector), metadata (jsonb)
  - chunk_index, ingested_at

ChatSession
  - id, user_id (FK User), title, created_at, updated_at

ChatMessage
  - id, session_id (FK ChatSession), role (user|assistant|system)
  - content
  - message_type: normal | clarification_request | clarification_response
  - sources_cited (jsonb)  ← populated when citations_enabled=true for source AND user preference=show
  - created_at, is_partial (bool — interrupted streams)

AgentRunState  (LangGraph checkpoint persistence)
  - thread_id (= session_id)
  - checkpoint_data (jsonb — serialized LangGraph state)
  - status: running | interrupted | completed | failed
  - interrupted_at_node (e.g. 'clarification_detector')
  - updated_at

LLMStageConfig  (system-level defaults, one row per named stage)
  - stage_name (PK), provider, model, api_key (encrypted)
  - base_url, temperature, max_tokens, context_window_tokens

SourceLLMConfig  (per-source overrides for retrieval and text_to_query stages only)
  - id, source_id (FK Source), stage: retrieval | text_to_query
  - provider, model, api_key (encrypted), base_url, temperature, max_tokens, context_window_tokens
  - UNIQUE(source_id, stage)

EmbeddingModelConfig  (registry of embedding models used across sources)
  - id, provider, model_name, vector_dimensions
  - created_at
  -- Sources FK to this; allows identifying all VectorChunks needing re-embedding when model changes

UserInvitation
  - id, email, role (admin|user), invitation_token_hash
  - invited_by (FK User), expires_at, accepted_at

PasswordResetToken
  - id, user_id (FK User), token_hash
  - expires_at, used_at, created_at

SyncLog
  - id, source_id (FK Source)
  - triggered_by: manual | scheduled | delta
  - triggered_at, completed_at, status
  - documents_added, documents_updated, documents_deleted, error_message

RefreshToken
  - id, user_id (FK User)
  - token_hash (hashed opaque token)
  - expires_at, revoked_at, created_at

CompanyPolicy  (one active record per deployment)
  - id, rules_text (plain language rules for both Guard nodes)
  - is_active: bool
  - created_by (FK User), created_at

CompanyPolicyVersion  (full history)
  - id, policy_id (FK CompanyPolicy)
  - rules_text, created_by (FK User), created_at

GuardrailEvent  (audit log of guard activations)
  - id, session_id (FK ChatSession), user_id (FK User)
  - guard_type: input | output
  - trigger_reason: jailbreak | policy_violation | data_leak | prompt_injection
  - original_input (text)           ← raw user message stored indefinitely; no masking, no TTL
  - sanitized_output (text)         ← output guard only; the cleaned response text
  - action_taken: blocked | sanitized | logged
  - created_at
  -- Note: full message text is retained for admin audit review. Deployment admins are responsible
  -- for ensuring this aligns with their internal data handling policies.
```

---

## 20. Open Questions & Backlog

### Decisions Pending

| # | Question | Notes |
|---|---|---|
| 1 | **Answer feedback** — Thumbs up/down to improve RAG quality over time? | Post-MVP |
| 2 | **API access** — Should users/systems be able to query the agent via API key (not just UI)? | Post-MVP |
| 3 | **Long-term memory** — Cross-session user memory store? | Post-MVP |
| 4 | **Reranking** — Cross-encoder reranking step between retrieval and synthesis? | Post-MVP |
| 5 | **BM25 / keyword fallback** — Behavior when vector search returns empty/low-quality results? | Post-MVP |
| 6 | **User data export/deletion** — Privacy compliance (GDPR etc.) | Not addressed; may be legally required depending on deployment region |
| 7 | **TLS/HTTPS** — Reverse proxy (nginx/Traefik) in Docker Compose? | Recommended before any production deployment; out of MVP Docker Compose scope |
| 8 | **Secrets management** — Docker secrets / Vault vs `.env` file? | `.env` for MVP; must be replaced before customer-facing deployment |

### Resolved Decisions

| # | Decision | Resolution |
|---|---|---|
| ✅ | File upload storage | **MinIO** (self-hosted, S3-compatible, Docker Compose service) |
| ✅ | Citations | Per-source admin toggle + per-user preference override; both stored in DB |
| ✅ | Citation UI style | **Inline footnotes** `[1][2]` in answer text + collapsible references section. SSE `citations` event carries citation metadata. |
| ✅ | Delta sync strategy (MVP) | **Polling** — timestamp column for DBs, content hash for files. CDC (Debezium) deferred post-MVP. |
| ✅ | Delta sync in MVP scope | **In MVP** — all three sync modes (manual, scheduled, delta) ship in MVP. |
| ✅ | MongoDB Text-to-Query in MVP | **In MVP** — `MongoQueryTool` ships in MVP alongside SQL. |
| ✅ | Description Auto-Refresh in MVP | **In MVP** — diff-review-approve flow ships in MVP. |
| ✅ | Clarifying questions in MVP | **In MVP** — LangGraph `interrupt()` + checkpoint persistence; SSE event type `clarification_needed`; stored as typed `ChatMessage` rows. |
| ✅ | Reflection Node default | **Disabled by default** — enabled via `REFLECTION_ENABLED=true` env var or admin settings UI. |
| ✅ | User access model | **Admin invite-only** — admin sends invitation link; no self-registration endpoint. `UserInvitation` table manages lifecycle. |
| ✅ | GuardrailEvent storage | **Store full message indefinitely, no masking, no TTL** — admin responsibility to manage per internal policy. |
| ✅ | DB migration tool | **Alembic** — standard SQLAlchemy migration tool for Python/FastAPI/PostgreSQL. |
| ✅ | IoC / Dependency Injection | `dependency-injector` library; all services depend on abstract interfaces (Protocols) |
| ✅ | Live vs Snapshot sources | Formalized as `source_mode`. DB sources support `vector_only`, `text_to_query`, or `hybrid` retrieval. SQL via `SQLDatabaseToolkit`; MongoDB via custom `MongoQueryTool`. Read-only enforced at connector level. |
| ✅ | NoSQL Text-to-Query | Custom `MongoQueryTool` built on `BaseTool`. LLM generates MQL as structured JSON. Only `find`/`aggregate` allowed. `$merge`, `$out`, write ops blocked at `validate_query_safety()`. |
| ✅ | Agent guardrails | Input Guard (jailbreak + policy check) + Output Guard (data leak scan + policy check) wrap the pipeline. `CompanyPolicy` admin-configured. `GuardrailEvent` audit log. |
| ✅ | AuthN | JWT (15 min) + httpOnly refresh token (7 days, rotated). bcrypt passwords. |
| ✅ | AuthZ | 4-layer enforcement: route RBAC → resource source access → DTO serialization → LLM context isolation. Connection strings and file paths structurally excluded from all API responses. |

### Assumptions to Validate

- pgvector provides sufficient vector search performance at expected data volumes
- A single Celery worker is sufficient for ingestion load at MVP scale
- Token streaming via SSE is compatible with anticipated Next.js deployment setups
