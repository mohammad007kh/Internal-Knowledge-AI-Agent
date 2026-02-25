# Data Model — Internal Knowledge AI Agent

**Generated**: 2026-02-25 | **Branch**: `001-knowledge-ai-agent`
**Source**: PRD v0.6 §17 + spec.md entities + clarification decisions

---

## PostgreSQL Extensions

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
```

---

## Tables

### `users`

Stores all user accounts (admin and regular users). Created exclusively via bootstrap or invitation — no self-registration.

```sql
CREATE TABLE users (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email               TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,          -- bcrypt hash
    role                TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users (email);
```

---

### `invitations`

Time-limited invitation tokens sent to new users by admins.

```sql
CREATE TABLE invitations (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email       TEXT NOT NULL,
    role        TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    token_hash  TEXT NOT NULL UNIQUE,           -- bcrypt hash of raw token
    invited_by  UUID NOT NULL REFERENCES users(id) ON DELETE SET NULL,
    expires_at  TIMESTAMPTZ NOT NULL,           -- default: NOW() + INTERVAL '48 hours'
    accepted_at TIMESTAMPTZ,                    -- NULL = pending
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_invitations_email ON invitations (email);
CREATE INDEX idx_invitations_token_hash ON invitations (token_hash);
```

---

### `password_reset_tokens`

One-time tokens for password reset flow.

```sql
CREATE TABLE password_reset_tokens (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,           -- default: NOW() + INTERVAL '1 hour'
    used_at     TIMESTAMPTZ,                    -- NULL = unused
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_prt_user_id ON password_reset_tokens (user_id);
```

---

### `sources`

Registered internal data sources. A source has a type (database or document collection) and a mode (live or snapshot).

```sql
CREATE TABLE sources (
    id                TEXT NOT NULL DEFAULT 'snapshot',  -- 'live' | 'snapshot'
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name              TEXT NOT NULL,
    description       TEXT,                              -- LLM-generated plain-language description
    type              TEXT NOT NULL CHECK (type IN ('database', 'document')),
    mode              TEXT NOT NULL CHECK (mode IN ('live', 'snapshot')),
    is_approved       BOOLEAN NOT NULL DEFAULT FALSE,    -- admin must approve before queryable
    citations_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by        UUID REFERENCES users(id) ON DELETE SET NULL,
    deleted_at        TIMESTAMPTZ,                       -- soft delete
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sources_deleted_at ON sources (deleted_at) WHERE deleted_at IS NULL;
```

---

### `source_connections`

Encrypted connection configuration per source. Connection strings and credentials never stored in plaintext.

```sql
CREATE TABLE source_connections (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id        UUID NOT NULL UNIQUE REFERENCES sources(id) ON DELETE CASCADE,
    connector_type   TEXT NOT NULL,             -- 'postgres' | 'mssql' | 'mysql' | 'mongodb' | 'document'
    config_encrypted BYTEA NOT NULL,            -- Fernet-encrypted JSON of connection params
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### `source_access`

Explicit user-to-source access grants. A user only sees data from sources they have been granted.

```sql
CREATE TABLE source_access (
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_id   UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    granted_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, source_id)
);

CREATE INDEX idx_source_access_source_id ON source_access (source_id);
```

---

### `source_llm_configs`

Per-source LLM slot overrides for specific pipeline stages (retrieval and text_to_query only).

```sql
CREATE TABLE source_llm_configs (
    source_id   UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    stage       TEXT NOT NULL CHECK (stage IN ('retrieval', 'text_to_query')),
    llm_slot_id UUID NOT NULL REFERENCES llm_configurations(id) ON DELETE RESTRICT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, stage)
);
```

---

### `source_sync_configs`

Per-source sync scheduling configuration.

```sql
CREATE TABLE source_sync_configs (
    source_id       UUID PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    mode            TEXT NOT NULL DEFAULT 'manual' CHECK (mode IN ('manual', 'scheduled', 'delta')),
    cron_expression TEXT,                       -- NULL if mode = 'manual'
    last_synced_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

### `sync_logs`

Audit history of all sync operations per source.

```sql
CREATE TABLE sync_logs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id       UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    triggered_by    UUID REFERENCES users(id) ON DELETE SET NULL,  -- NULL if Celery Beat
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    records_added   INTEGER NOT NULL DEFAULT 0,
    records_changed INTEGER NOT NULL DEFAULT 0,
    records_deleted INTEGER NOT NULL DEFAULT 0,
    error_detail    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sync_logs_source_id ON sync_logs (source_id);
CREATE INDEX idx_sync_logs_started_at ON sync_logs (started_at DESC);
```

---

### `document_chunks`

Chunked, embedded document and database content. The core vector search table.

```sql
CREATE TABLE document_chunks (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id     UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    chunk_text    TEXT NOT NULL,
    embedding     VECTOR(1536) NOT NULL,        -- OpenAI text-embedding-3-small; dimension matches embedding_model_configs
    metadata      JSONB NOT NULL DEFAULT '{}',  -- {"document_name": "...", "page": 3, "row_id": null}
    document_name TEXT,
    page_or_row   INTEGER,
    chunk_index   INTEGER NOT NULL DEFAULT 0,   -- position within document
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW index for approximate nearest-neighbor search
CREATE INDEX ON document_chunks
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

CREATE INDEX idx_document_chunks_source_id ON document_chunks (source_id);
```

---

### `chat_sessions`

Per-user conversation threads, persistent across sessions.

```sql
CREATE TABLE chat_sessions (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      TEXT,                            -- auto-generated from first message
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chat_sessions_user_id ON chat_sessions (user_id);
```

---

### `chat_messages`

Individual turns in a conversation. Includes user messages, assistant answers, clarification questions, and guardrail blocks.

```sql
CREATE TABLE chat_messages (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id        UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role              TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'clarification')),
    content           TEXT NOT NULL,
    citations         JSONB,                    -- [{"index": 1, "source": "...", "document": "...", "excerpt": "..."}]
    guardrail_blocked BOOLEAN NOT NULL DEFAULT FALSE,
    usage             JSONB,                    -- {"prompt_tokens": 312, "completion_tokens": 128}
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chat_messages_session_id ON chat_messages (session_id);
CREATE INDEX idx_chat_messages_created_at ON chat_messages (created_at);
```

---

### `company_policies`

Plain-language guardrail rules configured by admins. Applied to all conversations system-wide.

```sql
CREATE TABLE company_policies (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_text   TEXT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_company_policies_active ON company_policies (is_active) WHERE is_active = TRUE;
```

---

### `guardrail_events`

Immutable audit log of every guardrail activation. Records are retained indefinitely.

```sql
CREATE TABLE guardrail_events (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    message_id       UUID REFERENCES chat_messages(id) ON DELETE SET NULL,
    policy_id        UUID REFERENCES company_policies(id) ON DELETE SET NULL,  -- NULL for baseline protections
    original_content TEXT NOT NULL,
    trigger_reason   TEXT NOT NULL,
    action_taken     TEXT NOT NULL CHECK (action_taken IN ('blocked', 'sanitized')),
    stage            TEXT NOT NULL CHECK (stage IN ('input', 'output')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_guardrail_events_created_at ON guardrail_events (created_at DESC);
CREATE INDEX idx_guardrail_events_policy_id ON guardrail_events (policy_id);
-- No DELETE or UPDATE permitted on this table (audit integrity)
```

---

### `llm_configurations`

Named LLM slots — up to 10 active configurations. Each slot is independently assignable to pipeline stages.

```sql
CREATE TABLE llm_configurations (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slot_name       TEXT NOT NULL UNIQUE,       -- e.g., 'default', 'fast', 'reasoning'
    provider        TEXT NOT NULL,              -- 'openai' | 'anthropic' | 'azure_openai' | 'local'
    model_name      TEXT NOT NULL,              -- e.g., 'gpt-4o', 'claude-3-5-sonnet-20241022'
    temperature     FLOAT NOT NULL DEFAULT 0.1,
    max_tokens      INTEGER NOT NULL DEFAULT 2048,
    api_key_encrypted BYTEA,                   -- NULL for local/endpoint-only providers
    extra_config    JSONB NOT NULL DEFAULT '{}',-- provider-specific params (base_url, etc.)
    is_default      BOOLEAN NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT one_default CHECK (
        NOT is_default OR (SELECT COUNT(*) FROM llm_configurations WHERE is_default) <= 1
    )
);

CREATE UNIQUE INDEX idx_llm_config_one_default ON llm_configurations (is_default) WHERE is_default = TRUE;
```

---

### `embedding_model_configs`

Active embedding model configuration. Only one row can be `is_active = TRUE` at a time.

```sql
CREATE TABLE embedding_model_configs (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider     TEXT NOT NULL,
    model_name   TEXT NOT NULL,
    dimensions   INTEGER NOT NULL,             -- must match VECTOR(...) in document_chunks
    api_key_encrypted BYTEA,
    is_active    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_embedding_one_active ON embedding_model_configs (is_active) WHERE is_active = TRUE;
```

---

### `system_health_events`

FR-033: Immutable log of component crash and restart events.

```sql
CREATE TABLE system_health_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    component_name  TEXT NOT NULL,             -- 'worker' | 'beat' | 'backend' | 'frontend'
    event_type      TEXT NOT NULL CHECK (event_type IN ('crash', 'restart_attempt', 'restart_ok', 'restart_failed')),
    attempt_number  INTEGER,                   -- 1-3 for restart_attempt; 3 for restart_failed
    error_detail    TEXT,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_health_events_timestamp ON system_health_events (timestamp DESC);
CREATE INDEX idx_health_events_component ON system_health_events (component_name);
```

---

## Tenant Isolation Strategy

Model: **Single-tenant** — one deployment per organisation.

- No `tenant_id` column required on any table.
- User isolation enforced via `source_access` join in all agent queries.
- `AgentState.accessible_source_ids` is populated per-user at query start from `source_access`; the retriever and text_to_query nodes only search within these IDs.
- No naked queries against `document_chunks` without a `source_id = ANY(accessible_source_ids)` filter.

---

## Soft Delete Strategy

Tables with soft delete: `sources` (via `deleted_at` column).

- All queries against `sources` add `WHERE deleted_at IS NULL` filter (enforced via SQLAlchemy query wrapper).
- `document_chunks` for soft-deleted sources are hard-deleted via cascade on permanent deletion (admin action).

---

## Audit Columns

All tables include `created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.
Tables that change over time also include `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`.
`updated_at` is kept current via SQLAlchemy `onupdate` event.

---

## Migration Notes

- Tool: **Alembic** (versioned migrations)
- Strategy: `versioned` — sequential numbered migration files, no expand/contract for MVP
- Initial migration: creates pgvector extension, all tables, all indexes, and seeds an initial `embedding_model_configs` row (OpenAI `text-embedding-3-small`, 1536 dimensions, `is_active=TRUE`)
- Subsequent migrations: one migration file per schema change; never edit historical migration files
