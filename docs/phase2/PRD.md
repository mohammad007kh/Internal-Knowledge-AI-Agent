# Phase 2 PRD — Internal Knowledge AI Agent
## Completion & Polish

> **Status:** Ready for Development
> **Version:** 1.0
> **Date:** 2026-04-21
> **Prepared for:** Speckit
> **Based on:** Original PRD (docs/PRD.md) + full codebase audit

---

## 0. How to Read This Document

This PRD describes **what still needs to be built**. The application already has a working skeleton — auth, user management, database models, a LangGraph RAG pipeline, and an admin analytics page. Everything in this document is a gap between the original product vision and the current implementation.

Each section includes:
- **What exists today** — a brief honest description of the current state
- **What must be built** — the full specification
- **Acceptance criteria** — how to verify it is done correctly

The tech stack is fixed:
- **Backend:** Python 3.12, FastAPI, SQLAlchemy (async), PostgreSQL + pgvector, Celery + Redis, MinIO
- **Frontend:** Next.js 15 (App Router), React, TypeScript, Tailwind CSS v4, shadcn/ui, TanStack Query v5, Axios
- **AI:** LangGraph, LangChain, OpenAI (default), Langfuse tracing
- **DI:** `dependency-injector` library — all services wired via `Container` in `backend/src/core/container.py`

---

## 1. Priority Classification

| Priority | Label | Meaning |
|---|---|---|
| P0 | **Critical** | App is broken or misleading without this |
| P1 | **Core** | Core value proposition — ships before any user sees the product |
| P2 | **Important** | Needed for a complete admin experience |
| P3 | **Enhancement** | Improves polish and usability |

---

## 2. Source Registration — Type-Aware Wizard (P0)

### 2.1 What Exists Today

The `/admin/sources/new` page presents a single JSON textarea for `connection_config`. This exposes the internal encrypted model directly, forces admins to know the exact JSON schema per connector type, and provides no guidance. File sources are not supported at all. There is no AI description generation step.

### 2.2 What Must Be Built

A **multi-step guided wizard** that replaces the current raw-JSON form. The wizard must be smart enough to show the right form fields for each source type.

#### Step 1 — Source Type Selection

Display a grid of source type cards. Each card has an icon, a name, and a one-line description.

**Source types to support:**

| Category | Type Key | Display Name |
|---|---|---|
| Relational DB | `postgresql` | PostgreSQL |
| Relational DB | `mysql` | MySQL |
| Relational DB | `mssql` | MS SQL Server |
| NoSQL | `mongodb` | MongoDB |
| Documents | `pdf` | PDF Files |
| Documents | `docx` | Word Documents |
| Documents | `xlsx` | Excel Spreadsheets |
| Documents | `csv` | CSV Files |
| Documents | `txt` | Plain Text |
| Documents | `markdown` | Markdown |
| Web | `web_url` | Web Page / URL |
| Integrations | `confluence` | Confluence |
| Integrations | `sharepoint` | SharePoint |

Selecting a type advances to Step 2.

#### Step 2 — Connection Details

Show a type-appropriate form. Never a JSON textarea.

**For PostgreSQL / MySQL / MS SQL:**
```
Source Name            [text input, required]
Host                   [text input, required]
Port                   [number input, default: 5432 / 3306 / 1433]
Database Name          [text input, required]
Username               [text input, required]
Password               [password input, required]
SSL Mode               [select: disable / require / verify-ca / verify-full]
[Test Connection]  →  shows success/failure inline, never blocks progression
```

**For MongoDB:**
```
Source Name            [text input, required]
Connection URI         [text input, required, placeholder: mongodb://user:pass@host:27017]
Database Name          [text input, required]
Collection(s)          [text input, comma-separated, leave blank = all collections]
[Test Connection]
```

**For File Sources (PDF / DOCX / XLSX / CSV / TXT / Markdown):**
```
Source Name            [text input, required]
Upload File(s)         [drag-and-drop zone + file picker button]
                       [supports multiple files of matching type]
                       [max 50 MB per file]
                       [shows upload progress per file]
```

File upload uses the **presigned URL flow** (see section 2.5).

**For Web URL:**
```
Source Name            [text input, required]
URL                    [text input, URL validation]
Crawl Depth            [number, 0 = single page, max 3]
[Test Connection]
```

**For Confluence:**
```
Source Name            [text input, required]
Confluence Base URL    [text input]
Space Key(s)           [text input, comma-separated]
API Token              [password input]
Email                  [text input]
[Test Connection]
```

**For SharePoint:**
```
Source Name            [text input, required]
Site URL               [text input]
Client ID              [text input]
Client Secret          [password input]
Tenant ID              [text input]
[Test Connection]
```

#### Step 3 — AI Description Generation

After connection details are confirmed:

1. Show a loading state: *"Inspecting source schema..."*
2. Backend calls the connector's `inspect_schema()` or `load_documents()` briefly
3. OpenAI generates a natural language description: *"This PostgreSQL database contains employee records across 12 tables, including HR data, payroll, department hierarchies, and project assignments..."*
4. Display the generated description in an **editable textarea** — admin must be able to refine it
5. Admin clicks **"Approve Description"** to continue

If AI generation fails, skip gracefully and let the admin type a description manually.

#### Step 4 — Configuration

```
Sync Mode              [radio: Manual / Scheduled / Delta]
  if Scheduled:
    Schedule           [cron expression input with plain-language preview]
                       e.g. "0 2 * * *" → "Every day at 2:00 AM"
  if Delta (DB sources only):
    Timestamp Column   [text input, e.g. "updated_at"]

Retrieval Mode         [radio — DB sources only]
  ○ Vector Only        (semantic search over ingested snapshots)
  ○ Text to Query      (live SQL/MongoDB query generation)
  ○ Hybrid             (agent decides per query)

Citations Enabled      [toggle: ON / OFF]
  if ON:
    Description shown in answers — source name may appear in citations
  if OFF:
    Source name is never revealed in answers
```

#### Step 5 — Review & Save

Summary card showing all entered values. "Create Source" button submits.

On success: redirect to `/admin/sources/[id]` with a success toast. A background Celery sync job is immediately triggered if sync mode is Manual (first-time ingestion).

### 2.3 Backend Changes Required

**New endpoint:** `POST /api/v1/sources/inspect`
- Accepts: `{ source_type, config }` (unencrypted — this is a preview call, not a save)
- Returns: `{ description: string, schema_summary: object }`
- Calls connector `inspect_schema()` / `load_documents()` briefly
- Calls OpenAI to generate the description
- Does NOT persist anything

**Modify:** `POST /api/v1/sources` to accept structured fields instead of raw `config` blob:
```json
{
  "name": "HR Database",
  "source_type": "postgresql",
  "connection": {
    "host": "db.internal",
    "port": 5432,
    "database": "hrdb",
    "username": "readonly",
    "password": "secret",
    "ssl_mode": "require"
  },
  "description": "Contains employee and payroll data...",
  "sync_mode": "scheduled",
  "sync_schedule": "0 2 * * *",
  "retrieval_mode": "hybrid",
  "citations_enabled": true
}
```

The backend assembles the `connection_config` JSON and Fernet-encrypts it before storing. The frontend never handles encryption.

**New endpoint:** `POST /api/v1/sources/upload-url`
- Admin-only
- Accepts: `{ filename: string, content_type: string }`
- Returns: `{ upload_url: string, object_key: string }` (presigned MinIO PUT URL, 15-minute TTL)
- Frontend uploads directly to MinIO using the presigned URL
- Frontend then calls `POST /api/v1/sources` with `object_key` instead of connection details

### 2.4 Source Type in API Responses

`GET /api/v1/sources` and `GET /api/v1/sources/[id]` must return:
```json
{
  "id": "uuid",
  "name": "HR Database",
  "source_type": "postgresql",
  "source_mode": "live",
  "retrieval_mode": "hybrid",
  "description": "...",
  "status": "ready",
  "citations_enabled": true,
  "sync_mode": "scheduled",
  "sync_schedule": "0 2 * * *",
  "last_synced_at": "2026-04-20T02:00:00Z",
  "created_at": "...",
  "document_count": 1842,
  "chunk_count": 9431
}
```

`connection_config`, `file_storage_path`, and internal IDs must never appear in responses.

### 2.5 File Upload — Presigned URL Flow

```
Frontend                          Backend                    MinIO
   |                                 |                          |
   |-- POST /sources/upload-url ---> |                          |
   |   { filename, content_type }    |-- generate presigned --> |
   |                                 |   PUT URL (15 min TTL)   |
   |<-- { upload_url, object_key } --|                          |
   |                                 |                          |
   |-- PUT {upload_url} (file) -----------------------------> |
   |   (direct, bypasses backend)                              |
   |<-- 200 OK -------------------------------------------- |
   |                                 |                          |
   |-- POST /sources ---------------> |                          |
   |   { name, source_type: "pdf",   |                          |
   |     object_key, description, .. }                          |
   |<-- 201 Created -----------------|                          |
```

The file **never passes through the FastAPI backend**. This is required to prevent memory exhaustion on large files.

### 2.6 Acceptance Criteria

- [ ] Admin can add a PostgreSQL source using host/port/db/user/password fields
- [ ] Admin can add a PDF source by dragging and dropping files
- [ ] Test Connection shows success/failure without leaving the wizard
- [ ] AI generates a description after connection; admin can edit it
- [ ] Form validates required fields per source type before allowing Next
- [ ] After saving, source appears in the list with correct type icon and status "pending"
- [ ] Celery sync job is triggered immediately on first save

---

## 3. Sources List Page — Completion (P1)

### 3.1 What Exists Today

A basic table with source name and a delete button. No type icons, no status badges, no sync controls, no document counts, no description preview.

### 3.2 What Must Be Built

**Sources table columns:**
| Column | Content |
|---|---|
| Type icon | Icon matching source type (database, file, web, etc.) |
| Name | Source name, clickable → detail page |
| Status | Badge: `pending` (gray) / `ingesting` (blue, animated) / `ready` (green) / `error` (red) / `stale` (amber) / `paused` (gray) |
| Mode | Badge: `Live` (green outline) / `Snapshot` (gray outline) |
| Documents | Count of ingested documents |
| Last Synced | Relative time ("3 hours ago") or "Never" |
| Actions | Sync Now, Edit, Delete |

**Sync Now button:**
- Triggers `POST /api/v1/sources/{id}/sync`
- Button shows a spinner while job is running
- Polls `GET /api/v1/sources/{id}/sync-jobs` every 5 seconds to update status
- Shows inline success/error toast when job completes

**Search & Filter:**
- Text search by source name (client-side filter)
- Filter by type (dropdown: All / Database / File / Web / Integration)
- Filter by status (dropdown: All / Ready / Error / Ingesting)

### 3.3 Source Detail Page — Completion (P1)

**What exists today:** A form that re-exposes the raw JSON config.

**What must be built:**

The source detail page at `/admin/sources/[id]` must show:

**Header section:**
- Source name (editable inline)
- Type badge + Mode badge + Status badge
- Last synced time + document count

**Tabs:**

**Overview tab:**
- AI-generated description (editable textarea + Save button)
- "Refresh Description" button → calls `POST /api/v1/sources/inspect` with current config, shows new AI-generated description in a diff-style modal, admin approves or dismisses
- Retrieval mode (editable for DB sources)
- Citations enabled toggle

**Sync tab:**
- Sync mode (Manual / Scheduled / Delta) — editable
- Schedule expression with plain-language preview
- "Sync Now" button
- Sync history table: triggered_at, duration, status, documents_synced, error_message (if any)

**Access tab:**
- Table of users with access to this source
- "Grant Access" — user search input + Add button
- "Revoke" button per user

**Settings tab:**
- Rename source
- Connection details (show redacted — "●●●●●●●●" for password, host/port visible)
- "Update Connection" button → opens wizard Step 2 pre-filled
- Danger zone: Delete source (with confirmation dialog warning about vector cleanup)

### 3.4 New Backend Endpoints Required

`GET /api/v1/sources/{id}/stats`
- Returns: `{ document_count, chunk_count, last_synced_at, sync_job_count }`

`POST /api/v1/sources/{id}/refresh-description`
- Re-runs schema inspection + AI generation
- Returns: `{ proposed_description: string }`
- Does NOT save — admin must explicitly approve via `PATCH /api/v1/sources/{id}`

### 3.5 Acceptance Criteria

- [ ] Sources list shows type icon, status badge, mode badge, document count, last synced
- [ ] Sync Now button works and shows live progress
- [ ] Source detail has Overview / Sync / Access / Settings tabs
- [ ] "Refresh Description" proposes new text; admin approves or dismisses
- [ ] Sync history table shows past jobs with error details
- [ ] Access tab allows grant/revoke per user

---

## 4. Chat Interface — Completion (P0)

### 4.1 What Exists Today

Chat components exist as files (`ChatLayout`, `MessageThread`, `ChatInputBar`, `SessionList`, `SourceSelector`, `CitationPanel`, `ClarificationCard`) and are partially implemented. The core SSE streaming connection to the backend pipeline is the critical unknown.

### 4.2 Backend Chat API

**Endpoint:** `POST /api/v1/chat/sessions/{session_id}/messages`
- Auth: any authenticated user
- Body: `{ content: string, source_ids?: string[] }`
- Response: `text/event-stream` (SSE)

**SSE Event Types:**

```
event: token
data: {"delta": "The quarterly revenue..."}

event: clarification_needed
data: {"question": "Are you asking about Q3 or Q4?"}

event: guardrail_blocked
data: {"message": "I'm not able to help with that request."}

event: citations
data: {"citations": [{"ref": 1, "source_name": "Finance DB", "excerpt": "...", "page": null}]}

event: done
data: {"session_id": "uuid", "message_id": "uuid", "total_tokens": 842}

event: error
data: {"message": "Pipeline error. Please try again."}
```

The backend must:
1. Look up the session and verify user owns it
2. Intersect `source_ids` with sources the user has access to
3. Persist the user's message to `chat_messages`
4. Run the LangGraph pipeline asynchronously, streaming tokens via SSE
5. On `done`: persist the assistant's complete message to `chat_messages`

**Session endpoints (complete):**

`GET /api/v1/chat/sessions` — list user's sessions (already returns 200 ✓)

`POST /api/v1/chat/sessions` — create new session
- Body: `{ title?: string, source_ids?: string[] }`
- Returns: `{ id, title, created_at }`

`PATCH /api/v1/chat/sessions/{id}` — rename session
- Body: `{ title: string }`

`DELETE /api/v1/chat/sessions/{id}` — soft-delete session

`GET /api/v1/chat/sessions/{id}/messages` — load message history
- Returns: `{ messages: [{ id, role, content, created_at, sources_cited? }] }`

### 4.3 Frontend Chat Requirements

**Session sidebar:**
- Lists all sessions, sorted by updated_at desc
- "New Chat" button at top
- Each session shows: title, last message preview (truncated to 60 chars), relative time
- Active session highlighted
- Right-click or hover → "Rename" / "Delete" actions
- Sessions are lazy-loaded (paginated, infinite scroll)

**Message thread:**
- User messages: right-aligned, user avatar/initials
- Assistant messages: left-aligned, app icon
- Streaming token display: text appears token by token, cursor blinking at end
- Citations rendered inline as `[1]` superscript links that expand a citation panel below the message
- `clarification_needed` event renders a distinct card: *"Could you clarify...?"* with a reply input
- `guardrail_blocked` renders a red alert card
- Loading state: skeleton while waiting for first token
- Scroll-to-bottom behavior: auto-scroll while streaming, stops if user scrolls up

**Source selector:**
- Shown at the top of the chat input bar
- Multi-select from sources the user has access to (fetched from `GET /api/v1/users/me/sources`)
- Selected sources are persisted to the session on first message
- Shows source type icons + names
- "All accessible sources" is the default (empty array = use all)

**Input bar:**
- Textarea (auto-resizing, max 5 rows)
- Send button (disabled while streaming)
- Stop button (replaces Send while streaming — calls `AbortController.abort()` on the fetch)
- Keyboard: Enter to send, Shift+Enter for new line
- Character counter at 2000+ chars

**Citation panel:**
- Appears below the message when citations are present
- Each citation: `[n] Source Name — doc_name, page X — "excerpt..."`
- Collapsible (collapsed by default)

**Clarification flow:**
- When `clarification_needed` SSE event arrives, streaming stops
- A card appears: the question text + a text input + "Reply" button
- User types their answer, clicks Reply
- Frontend sends a new message to the same session with the answer
- Pipeline resumes from the interrupted state

### 4.4 Acceptance Criteria

- [ ] Sending a message streams tokens in real time
- [ ] Citations appear after the response with inline `[1]` markers
- [ ] Clarification cards render and accept user reply
- [ ] Guardrail blocked messages render distinctly
- [ ] Stop button aborts the stream mid-response
- [ ] Session history loads correctly when switching sessions
- [ ] Rename and delete work on sessions
- [ ] Source selector filters which sources the pipeline uses

---

## 5. LLM Settings Admin Page (P1)

### 5.1 What Exists Today

The `llm_configurations` table exists in the database. No admin UI exists to read or write it.

### 5.2 Page: `/admin/settings/llm`

Display one configuration card per pipeline stage:

| Stage | Description shown to admin |
|---|---|
| `schema_inspector` | AI that analyzes new sources and writes descriptions |
| `clarification_detector` | AI that decides when to ask a follow-up question |
| `query_analyzer` | AI that interprets and rewrites user queries |
| `source_router` | AI that picks which sources to search |
| `retrieval` | AI used during vector search reasoning |
| `text_to_query` | AI that generates SQL / MongoDB queries |
| `synthesizer` | AI that writes the final answer |
| `reflector` | AI that checks answer quality (disabled by default) |
| `input_guard` | AI that checks user messages for policy violations |
| `output_guard` | AI that checks answers before showing them |

Each card has:
```
Stage: Synthesizer
Description: [plain text explanation]

Provider     [select: OpenAI / Anthropic / Ollama / Azure OpenAI]
Model        [text input, e.g. gpt-4o]
API Key      [password input, shows "●●●● saved" if already set]
Base URL     [text input, only shown for Ollama/Azure]
Temperature  [slider 0.0–2.0, default 0.7]
Max Tokens   [number input]
[Save]  [Test Connection]
```

"Test Connection" sends a minimal completion request to verify the config works before saving.

Reflector stage has an additional **Enable/Disable toggle** at the top of its card (disabled by default per PRD).

### 5.3 Backend Endpoints Required

`GET /api/v1/admin/llm-settings` — returns all stage configs (API keys redacted to last 4 chars)

`PUT /api/v1/admin/llm-settings/{stage}` — update a single stage config

`POST /api/v1/admin/llm-settings/{stage}/test` — test connection for a stage config

### 5.4 Acceptance Criteria

- [ ] Admin can see all 10 pipeline stages
- [ ] Changing provider updates the model field placeholder accordingly
- [ ] API key shows redacted if already set; re-entering replaces it
- [ ] Test Connection returns pass/fail inline
- [ ] Saving triggers a toast; config is persisted and used by next pipeline run

---

## 6. Company Policy / Guardrails Admin Page (P1)

### 6.1 What Exists Today

`company_policies` table exists. `GuardrailService` uses it. No admin UI exists.

### 6.2 Page: `/admin/settings/policy`

**Active Policy section:**
```
Company Rules
[large textarea — plain language rules]
Example:
  - Never discuss competitor products.
  - Always respond formally.
  - Do not reveal salary data to users outside HR.

[Save Policy]
```

Below the textarea: read-only preview of what the input guard and output guard inject as a system prompt prefix.

**Guardrail Events section (audit log):**

Table: recent guardrail activations
| Time | User | Guard | Trigger | Action | View |
|---|---|---|---|---|---|
| 2h ago | alice@... | Input | jailbreak | blocked | [Details] |
| 1d ago | bob@... | Output | data_leak | sanitized | [Details] |

"Details" opens a modal showing the original input, the matched trigger reason, and what action was taken.

**Stats bar:**
- Total blocks this week
- Top trigger reason
- Most common user (for admin awareness)

### 6.3 Backend Endpoints Required

`GET /api/v1/admin/policy` — returns active policy text

`PUT /api/v1/admin/policy` — update policy (creates a new version, marks old as inactive)

`GET /api/v1/admin/guardrail-events` — paginated list of events (limit, offset, filter by guard_type)

`GET /api/v1/admin/guardrail-events/{id}` — full event detail including original_input

### 6.4 Acceptance Criteria

- [ ] Admin can read and update the company policy text
- [ ] Save creates a new version (history is preserved in DB)
- [ ] Guardrail events table shows recent activations
- [ ] Details modal shows full original message and action taken

---

## 7. Users Page — Completion (P1)

### 7.1 What Exists Today

A table listing users with role and deactivate controls. No source access management from this page.

### 7.2 What Must Be Enhanced

**Users table additions:**
- Last login column (relative time)
- Source access count ("3 sources")
- Status badge: Active (green) / Inactive (red)
- Filter: Active only (default) / All / Inactive

**User detail page `/admin/users/[id]` — add Source Access tab:**
```
Sources this user can access:
[Search sources...]

[ ] HR Database          (PostgreSQL)  [Revoke]
[x] Finance Reports      (Excel)       [Revoke]
[ ] Company Wiki         (Confluence)  [Revoke]

[+ Grant Access to a Source]  → searchable source dropdown
```

This currently has no UI. The backend endpoints (`POST/DELETE /api/v1/sources/{id}/permissions`) already exist.

**Invite user flow improvement:**
- Current: modal form
- Needed: also show pending invitations in a separate table on the users list page
  - Columns: email, role, invited by, expires at, [Resend] [Cancel]
  - Backend: `GET /api/v1/users/invitations` (add this endpoint) and `DELETE /api/v1/users/invitations/{id}` (cancel)

### 7.3 Acceptance Criteria

- [ ] Users list shows last login and source access count
- [ ] User detail page has Source Access tab with grant/revoke
- [ ] Pending invitations table shows on users list
- [ ] Invitation can be cancelled before it is accepted

---

## 8. Profile Page — Completion (P2)

### 8.1 What Exists Today

Exists as a page stub.

### 8.2 What Must Be Built

```
Profile

Email:         alice@company.com  (read-only)
Full Name:     [text input]       [Save]

Password
  Current password    [input]
  New password        [input]
  Confirm new         [input]
  [Change Password]

Preferences
  Citation display    [toggle: Show / Hide]
  Theme              [toggle: Light / Dark / System]
```

`PATCH /api/v1/users/me` — update full_name (add if missing)
`GET /api/v1/users/me` — already exists, must include full_name

### 8.3 Acceptance Criteria

- [ ] User can update their full name
- [ ] Password change works (uses existing `POST /api/v1/auth/change-password`)
- [ ] Citation preference is saved and used in chat

---

## 9. Navigation & Layout Completion (P1)

### 9.1 What Exists Today

The admin layout and sidebar exist but are incomplete. No navigation to LLM Settings or Policy pages. The structure is not clearly organized.

### 9.2 Required Sidebar Structure

**Admin sidebar:**
```
OVERVIEW
  Dashboard (analytics)

CONTENT
  Sources
  Connectors

USERS
  Users

SETTINGS
  LLM Configuration
  Company Policy

SYSTEM
  Health
```

**User sidebar (chat layout):**
```
[+ New Chat]
──────────────
RECENT
  [session title 1]
  [session title 2]
  ...
──────────────
[Profile]
[Sign Out]
```

### 9.3 Acceptance Criteria

- [ ] All admin pages reachable from sidebar
- [ ] Active page highlighted in sidebar
- [ ] Sidebar collapses to icons on small screens
- [ ] User sidebar shows sessions grouped by date ("Today", "Yesterday", "Last 7 days")

---

## 10. Missing Backend Endpoints — Summary (P1)

The following endpoints are needed but do not exist. Implement all with standard JWT auth, role checks, paginated responses where appropriate, and RFC 7807 problem details for errors.

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/sources/inspect` | admin | AI description generation (no persist) |
| POST | `/api/v1/sources/upload-url` | admin | Presigned MinIO PUT URL |
| POST | `/api/v1/sources/{id}/refresh-description` | admin | Re-run AI inspection, return proposed text |
| GET | `/api/v1/sources/{id}/stats` | admin | document_count, chunk_count |
| GET | `/api/v1/admin/llm-settings` | admin | All stage LLM configs (keys redacted) |
| PUT | `/api/v1/admin/llm-settings/{stage}` | admin | Update one stage config |
| POST | `/api/v1/admin/llm-settings/{stage}/test` | admin | Test LLM connection |
| GET | `/api/v1/admin/policy` | admin | Active company policy |
| PUT | `/api/v1/admin/policy` | admin | Update policy (versioned) |
| GET | `/api/v1/admin/guardrail-events` | admin | Paginated guardrail audit log |
| GET | `/api/v1/admin/guardrail-events/{id}` | admin | Full event detail |
| GET | `/api/v1/users/invitations` | admin | Pending invitations |
| DELETE | `/api/v1/users/invitations/{id}` | admin | Cancel invitation |
| PATCH | `/api/v1/users/me` | any | Update own profile (full_name) |
| GET | `/api/v1/users/me` | any | Own user profile |
| PATCH | `/api/v1/chat/sessions/{id}` | owner | Rename session |
| DELETE | `/api/v1/chat/sessions/{id}` | owner | Soft-delete session |
| GET | `/api/v1/chat/sessions/{id}/messages` | owner | Load message history |
| POST | `/api/v1/chat/sessions/{id}/messages` | owner | Send message → SSE stream |

---

## 11. Data Model Changes Required

### 11.1 Source Model — Add Fields

The `sources` table is missing several fields from the PRD. Add via Alembic migration:

```sql
ALTER TABLE sources ADD COLUMN source_mode VARCHAR DEFAULT 'snapshot';
  -- Values: 'live' | 'snapshot'
  -- 'live' for DB connectors, 'snapshot' for file/web connectors

ALTER TABLE sources ADD COLUMN retrieval_mode VARCHAR DEFAULT 'vector_only';
  -- Values: 'vector_only' | 'text_to_query' | 'hybrid'
  -- Only meaningful when source_mode = 'live'

ALTER TABLE sources ADD COLUMN description TEXT;
  -- AI-generated, admin-approved description

ALTER TABLE sources ADD COLUMN sync_mode VARCHAR DEFAULT 'manual';
  -- Values: 'manual' | 'scheduled' | 'delta'

ALTER TABLE sources ADD COLUMN sync_schedule VARCHAR;
  -- Cron expression, e.g. '0 2 * * *'

ALTER TABLE sources ADD COLUMN last_synced_at TIMESTAMPTZ;

ALTER TABLE sources ADD COLUMN status VARCHAR DEFAULT 'pending';
  -- Values: 'pending' | 'ingesting' | 'ready' | 'error' | 'stale' | 'paused'

ALTER TABLE sources ADD COLUMN citations_enabled BOOLEAN DEFAULT TRUE;

ALTER TABLE sources ADD COLUMN file_storage_path VARCHAR;
  -- MinIO object key for file sources (INTERNAL ONLY — never in API responses)
```

### 11.2 User Model — Add Fields

```sql
ALTER TABLE users ADD COLUMN full_name VARCHAR;
ALTER TABLE users ADD COLUMN show_citations_preference BOOLEAN DEFAULT TRUE;
```

### 11.3 Chat Message Model — Add Fields

```sql
ALTER TABLE chat_messages ADD COLUMN sources_cited JSONB;
  -- Citation metadata: [{"ref": 1, "source_name": "...", "excerpt": "..."}]

ALTER TABLE chat_messages ADD COLUMN message_type VARCHAR DEFAULT 'normal';
  -- Values: 'normal' | 'clarification_request' | 'clarification_response' | 'guardrail_blocked'

ALTER TABLE chat_messages ADD COLUMN is_partial BOOLEAN DEFAULT FALSE;
  -- True if stream was interrupted before completion
```

### 11.4 New Table: source_description_history

```sql
CREATE TABLE source_description_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id UUID NOT NULL REFERENCES sources(id),
  description TEXT NOT NULL,
  replaced_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  replaced_by UUID REFERENCES users(id)
);
```

---

## 12. Connector Scheduling (P2)

### 12.1 What Exists Today

`trigger_all_syncs` Celery task exists but is not wired to Celery Beat with per-source schedules.

### 12.2 What Must Be Built

When a source is saved with `sync_mode = 'scheduled'` and a `sync_schedule` cron expression:
- Backend registers a Celery Beat periodic task for that source
- Task name: `sync_source_{source_id}`
- Uses `celery.conf.beat_schedule` updated dynamically (or `django-celery-beat` equivalent for dynamic schedules)
- On source update/delete: cancel the old periodic task, register updated one

### 12.3 Acceptance Criteria

- [ ] Source with sync_mode=scheduled auto-syncs per cron expression
- [ ] Updating the schedule on a source updates the Celery Beat entry
- [ ] Deleting a source cancels its scheduled task

---

## 13. Error States & Empty States (P2)

Every page must handle:

**Loading state:** skeleton loaders (already have shadcn Skeleton component)

**Empty state:** illustrated empty state with CTA when a list has no items:
- Sources list: *"No sources yet. Add your first knowledge source."* + "Add Source" button
- Users list: *"No users. Invite your team."* + "Invite User" button
- Chat sessions: *"Start a conversation to get answers from your knowledge base."* + "New Chat" button
- Sync history: *"No sync runs yet."*

**Error state:** when an API call fails:
- Inline error message with retry button
- Never leave the user looking at a blank page

**Network offline:** toast notification when the browser loses connectivity

---

## 14. Technical Constraints & Rules

These rules are **non-negotiable** — they reflect security and architecture decisions already made:

1. **Connection strings and API keys never appear in API responses.** Use the existing DTO pattern (`SourcePublic` vs `SourceInternal`). FastAPI `response_model` enforces this structurally.

2. **File bytes never pass through the FastAPI backend.** Always use MinIO presigned URLs for uploads.

3. **All new services must be registered in `backend/src/core/container.py`** and injected via FastAPI's `Depends()`. Never import services directly in routers.

4. **All new database access must go through a Repository class.** No raw SQL in services or routers.

5. **Alembic for all schema changes.** Never modify models without a corresponding migration.

6. **Frontend API calls go through `apiClient` in `src/lib/api-client.ts`.** Never use `fetch` or raw axios directly in components. Define typed functions in `src/lib/api/`.

7. **TanStack Query for all server state.** Never store server data in `useState`. Use `useQuery` and `useMutation`.

8. **SSE streaming uses the browser's native `EventSource` API or `fetch` with `ReadableStream`.** Do not use a library that buffers the stream.

9. **New backend routes must be protected with the correct auth dependency:** `get_current_user` for any authenticated user, `require_admin` for admin-only routes.

10. **Rate limiting is already applied globally.** Do not add per-endpoint rate limiting in routers — configure via `RATE_LIMIT_*` env vars in `backend/src/core/config.py`.

---

## 15. Out of Scope for Phase 2

The following items from the original PRD are explicitly deferred. Do not build these:

- Slack / Teams integration
- Answer feedback (thumbs up/down with ML training loop)
- Cross-session memory / long-term user memory store
- Cross-encoder reranking
- BM25 / keyword fallback for empty vector results
- Multi-tenancy
- SAML / OIDC SSO
- Kubernetes / Helm deployment
- CDC (Debezium) for delta sync
- API key management for programmatic access
- Audit log export / GDPR data export

---

## 16. Phasing Recommendation

Build in this order. Each phase is a shippable increment.

### Phase 2A — Make the core loop work end-to-end
1. Source registration wizard (section 2) — P0
2. Chat interface SSE streaming (section 4) — P0
3. Missing data model fields (section 11) — P0

### Phase 2B — Admin experience
4. Sources list + detail page completion (section 3) — P1
5. LLM Settings page (section 5) — P1
6. Company Policy page (section 6) — P1
7. Users page completion (section 7) — P1
8. Navigation & sidebar (section 9) — P1

### Phase 2C — Polish
9. Profile page (section 8) — P2
10. Connector scheduling (section 12) — P2
11. Empty states & error states (section 13) — P2

---

## Appendix A — File Structure Reference

```
backend/src/
  api/v1/
    sources.py        ← add inspect, upload-url, refresh-description, stats endpoints
    chat.py           ← add messages SSE endpoint, rename/delete session endpoints
    admin/
      llm_settings.py  ← NEW
      policy.py        ← NEW
      guardrails.py    ← NEW
  models/
    source.py         ← add fields: source_mode, retrieval_mode, description, sync_*, status, citations_enabled
    user.py           ← add fields: full_name, show_citations_preference
    chat.py           ← add fields: sources_cited, message_type, is_partial
    source_description_history.py  ← NEW
  repositories/
    llm_config_repository.py   ← NEW
    policy_repository.py       ← NEW
  services/
    llm_config_service.py      ← NEW
    policy_service.py          ← NEW
    source_inspection_service.py  ← NEW (wraps connector + OpenAI description gen)
  alembic/versions/
    0018_source_fields.py      ← add source_mode, retrieval_mode, description, etc.
    0019_user_fields.py        ← add full_name, show_citations_preference
    0020_chat_message_fields.py ← add sources_cited, message_type, is_partial
    0021_source_description_history.py ← new table

frontend/src/
  app/(dashboard)/
    chat/
      page.tsx              ← complete chat interface
    profile/
      page.tsx              ← complete profile page
  app/(dashboard)/admin/
    sources/
      new/page.tsx          ← replace with wizard
      [id]/page.tsx         ← complete with tabs
    settings/
      llm/page.tsx          ← NEW
      policy/page.tsx       ← NEW
    users/
      [id]/page.tsx         ← add Source Access tab
  components/
    chat/
      MessageThread.tsx     ← complete streaming + citations
      ClarificationCard.tsx ← complete
      CitationPanel.tsx     ← complete
    admin/
      SourceWizard/         ← NEW directory with step components
        StepSourceType.tsx
        StepConnectionForm.tsx
        StepAIDescription.tsx
        StepConfiguration.tsx
        StepReview.tsx
      LLMStageCard.tsx      ← NEW
      PolicyEditor.tsx      ← NEW
      GuardrailEventsTable.tsx ← NEW
  lib/api/
    llm-settings.ts         ← NEW
    policy.ts               ← NEW
    chat.ts                 ← NEW (SSE streaming, session CRUD)
```
