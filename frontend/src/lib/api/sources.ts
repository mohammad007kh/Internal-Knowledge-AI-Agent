import { apiClient } from '@/lib/api-client'

// ---------------------------------------------------------------------------
// Source domain types
// ---------------------------------------------------------------------------

// NOTE: the backend `SourceType` StrEnum (backend/src/models/enums.py) only
// emits FIVE values: 'web_url' | 'file_upload' | 'database' | 'confluence' |
// 'sharepoint'. The granular dialect (postgresql/mysql/…) lives separately in
// `connection.db_type`. The extra members below are kept for forward-compat /
// older fixtures but the gating helpers in sourceTypeMatrix.ts MUST recognise
// 'database' (it's what real DB sources actually carry).
export type SourceType =
  | 'web_url'
  | 'file_upload'
  | 'database'
  | 'confluence'
  | 'sharepoint'
  | 'google_drive'
  | 'notion'
  | 'postgresql'
  | 'mysql'
  | 'mssql'
  | 'mongodb'
  | 'pdf'
  | 'docx'
  | 'xlsx'
  | 'csv'
  | 'txt'
  | 'markdown'

export type SourceStatus = 'pending' | 'syncing' | 'ready' | 'error' | 'disabled'
export type SyncMode = 'manual' | 'scheduled' | 'delta'
export type SourceMode = 'snapshot' | 'live'
export type RetrievalMode = 'vector_only' | 'text_to_query' | 'hybrid'

// ---------------------------------------------------------------------------
// AI-naming bookkeeping (F9)
//
// `name_status` / `description_status` track whether each field was set by the
// user up front, is awaiting an AI-generated value, or has been written by the
// AI post-ingestion. Components branch on these to render the "Naming…"
// shimmer placeholder while the assistant is still reading the source.
// ---------------------------------------------------------------------------

/**
 * Provenance of a source's name or description field.
 *
 * - `user_set` — the admin typed it themselves at creation (or edited it later).
 * - `pending_ai` — the admin opted into auto-naming and the assistant has not
 *   yet produced a value; UI should render a shimmer pill.
 * - `ai_set` — the assistant wrote the value. Renders identically to
 *   `user_set` so admins don't have to know AI authored it (the bookkeeping
 *   exists so the future "Regenerate" affordance can target it).
 */
export type NameStatus = 'user_set' | 'pending_ai' | 'ai_set'

// ---------------------------------------------------------------------------
// DB-source studying agent (Wave 1A schema columns)
//
// These fields ship in the database in Wave 1A and are exposed on the
// `SourceListItem` payload in Wave 3 once the studying agent is merged. They
// are *optional* on the wire today — components must degrade gracefully when
// the API has not yet populated them.
// ---------------------------------------------------------------------------

// `schema_status` mirrors the LATEST study's lifecycle for the UI/list
// filters. The backend (see backend/src/tasks/study_source.py) emits
// lowercase: 'studying' transiently, then terminal 'completed' or 'failed'
// — null on sources that were never studied. The 'queued before any work'
// concept is NOT in this column; it lives on `study_state` (see StudyState
// below). The 'stale / drift' concept lives on `drift_signal_count`.
export type SchemaStatus = 'studying' | 'completed' | 'failed'

/**
 * Phase the studying agent is in. The backend names match the LangGraph
 * pipeline's node IDs. `READY_PARTIAL` means we shipped a usable schema doc
 * but at least one table failed AI description.
 */
export type StudyState =
  | 'QUEUED'
  | 'CONNECTING'
  | 'CONNECT_FAILED'
  | 'INVENTORY'
  | 'INVENTORY_FAILED'
  | 'COLUMNS'
  | 'COLUMNS_FAILED'
  | 'SAMPLING'
  | 'SAMPLING_FAILED'
  | 'DESCRIBING'
  | 'DESCRIBING_FAILED'
  | 'INDEXING'
  | 'INDEXING_FAILED'
  | 'READY'
  | 'READY_PARTIAL'

export interface SyncJob {
  id: string
  source_id: string
  /**
   * Lifecycle state. `cancelled` was added in U16 for cooperative
   * cancellation — a task that observed the Stop-sync signal at a safe
   * checkpoint, committed whatever was stable, and exited.
   */
  status: 'pending' | 'running' | 'completed' | 'failed' | 'success' | 'cancelled'
  started_at: string | null
  finished_at: string | null
  completed_at: string | null
  /** U16 — populated only when status='cancelled'. */
  cancelled_at?: string | null
  error_message: string | null
  documents_synced: number
  documents_indexed: number
  chunks_created: number
  created_at: string
  updated_at: string
}

export interface SourceListItem {
  id: string
  name: string
  source_type: SourceType
  is_active: boolean
  created_at: string
  // Phase-2 enriched fields (optional for backwards compatibility)
  source_mode?: SourceMode
  status?: SourceStatus
  sync_mode?: SyncMode
  last_synced_at?: string | null
  description?: string | null
  latest_job?: SyncJob | null
  // Ingestion counters surfaced on /admin/sources (IngestionStrip pip labels).
  document_count?: number
  chunk_count?: number
  has_upload?: boolean
  // DB-source studying agent (Wave 3 wires real values; today undefined for
  // every row — UI must fall back gracefully).
  schema_status?: SchemaStatus | null
  study_state?: StudyState | null
  tables_documented?: number | null
  tables_partial?: number | null
  last_error_phase?: string | null
  last_error_message?: string | null
  // Categorised DB connection-failure metadata + server-rendered admin copy
  // (set only when the retry seam classified a connect failure; the
  // headline/next_action are constant, credential-free sentences).
  failure_category?: string | null
  attempts_made?: number | null
  failure_headline?: string | null
  failure_next_action?: string | null
  // AI-naming bookkeeping (F9). Optional for backwards compatibility — older
  // backends may omit these entirely; the UI defaults to treating absent
  // values as `user_set`.
  name_status?: NameStatus
  description_status?: NameStatus
  auto_name_and_description?: boolean
  // R1 — additional Source fields the backend now serializes for the admin
  // UI: drift counter (DB sources), last study/sync-due timestamps, embedder
  // pin, owner. All optional for backwards compatibility.
  drift_signal_count?: number
  last_studied_at?: string | null
  next_sync_due_at?: string | null
  embedder_id?: string | null
  owner_id?: string | null
  // Slice A (R6 / connection health) — surfaced by the backend's connection
  // probe job. All optional so older payloads that don't include them simply
  // render the "no probe yet" path. `connection_status` is independent of
  // ingestion status: a source may be `ready` but `connection_status` may be
  // `degraded` after recent intermittent failures.
  connection_status?: 'healthy' | 'degraded' | 'failed' | 'unknown'
  connection_last_checked_at?: string | null
  connection_last_error?: string | null
}

export interface SourceDetail extends SourceListItem {
  source_mode: SourceMode
  retrieval_mode: RetrievalMode
  description: string | null
  sync_mode: SyncMode
  sync_schedule: string | null
  last_synced_at: string | null
  status: SourceStatus
  citations_enabled: boolean
  updated_at: string
  // U10 — enriched on the detail endpoint only (the list endpoint omits
  // both to avoid an N+1). `owner_email` is joined on `Source.owner_id`;
  // `schema_summary` is the studying agent's one-line schema description
  // from the latest *completed* SchemaStudy's persisted document JSON.
  // Both `null` when unavailable (no owner row / no completed study).
  owner_email: string | null
  schema_summary: string | null
}

export interface PaginatedSources {
  items: SourceListItem[]
  total: number
  limit: number
  offset: number
}

export interface SourceStats {
  document_count: number
  chunk_count: number
  last_synced_at: string | null
  sync_job_count: number
}

export interface PaginatedSyncJobs {
  items: SyncJob[]
  total: number
  limit: number
  offset: number
}

export interface CreateSourceRequest {
  name: string
  source_type: SourceType
  config: Record<string, unknown>
  /**
   * When true, the backend assigns a placeholder name + description and
   * schedules an AI-naming pass to fill them in after first ingestion.
   * Defaults to `false` server-side when omitted.
   */
  auto_name_and_description?: boolean
}

/**
 * PATCH /api/v1/sources/{id} payload.
 *
 * All fields are optional and additive — callers should send only the fields
 * they intend to change. The form on the source detail page diffs against the
 * loaded source and submits only the dirty fields.
 *
 * Schedule semantics (`sync_schedule`): a cron expression when `sync_mode ===
 * 'scheduled'`, otherwise `null`. Sending `null` clears any prior schedule.
 */
export interface UpdateSourceRequest {
  name?: string
  description?: string | null
  citations_enabled?: boolean
  is_active?: boolean
  retrieval_mode?: RetrievalMode
  sync_mode?: SyncMode
  sync_schedule?: string | null
  source_mode?: SourceMode
}

export interface TestConnectionResponse {
  success: boolean
  message: string
}

/**
 * POST /api/v1/sources/inspect — pre-persistence connection test.
 *
 * Mirrors the backend `SourceInspectRequest` schema. The `source_type` value
 * is the canonical backend `SourceType` enum value (e.g. `'database'`,
 * `'web_url'`, `'file_upload'`) — NOT the granular DB dialect. The DB
 * dialect (`postgresql` | `mysql` | `mssql` | `mongodb`) is carried inside
 * the `connection` dict as `db_type`.
 *
 * Used by the new-source wizard's "Test connection" button to validate the
 * typed connection before any Source row exists. The server never echoes the
 * submitted `connection` back — only a diagnostic description plus a small
 * schema summary.
 */
export interface InspectSourceRequest {
  source_type: string
  connection: Record<string, unknown>
}

export interface InspectSourceResponse {
  description: string
  schema_summary: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Source intent (004-agentic-pipeline, T-023 endpoints; client wired here)
//
// Mirrors contracts/intent-api.yaml exactly. The admin review surface
// (IntentSection) reads via getIntentApi, saves via putIntentApi (which flips
// `intent_status` → 'user_set' server-side), and (re)generates the AI draft
// via proposeIntentApi.
//
// `intent_status` ramp:
//   - pending_ai  — admin opted into AI authoring; the draft hasn't landed.
//   - ai_set      — the assistant wrote a draft; reviewing (Save) activates
//                   out-of-scope decline authority (FR-002).
//   - user_set    — an admin reviewed/edited; this is authoritative and the
//                   propose pass will no longer overwrite it.
// ---------------------------------------------------------------------------

export type IntentStatus = 'pending_ai' | 'ai_set' | 'user_set'

/** A single `cross_source_hints` entry — admin-authored, never AI-written. */
export interface CrossSourceHint {
  topic: string
  source_id: string
}

export interface SourceIntent {
  purpose: string | null
  example_questions: string[] | null
  out_of_scope: string[] | null
  cross_source_hints: CrossSourceHint[] | null
  intent_status: IntentStatus
  intent_updated_at: string | null
}

/**
 * PUT body. All fields optional and additive — a provided field replaces the
 * stored value; an omitted field is left untouched. The server runs STRICT
 * sanitization + cap enforcement and returns 422 (problem+json, field named)
 * on violation.
 */
export interface SourceIntentUpdate {
  purpose?: string | null
  example_questions?: string[] | null
  out_of_scope?: string[] | null
  cross_source_hints?: CrossSourceHint[] | null
}

export interface RefreshDescriptionResponse {
  proposed_description: string
}

export interface AutoNameResponse {
  proposed_name: string
  proposed_description: string
}

export interface SourceDocument {
  id: string
  source_id: string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface PaginatedDocuments {
  items: SourceDocument[]
  total: number
  limit: number
  offset: number
}

export interface SourcePermissionsResponse {
  user_ids: string[]
}

export interface GrantPermissionRequest {
  user_id: string
}

// ---------------------------------------------------------------------------
// Endpoints
// ---------------------------------------------------------------------------

export async function listSourcesApi(limit = 50, offset = 0): Promise<PaginatedSources> {
  const { data } = await apiClient.get<PaginatedSources>('/api/v1/sources', {
    params: { limit, offset },
  })
  return data
}

export async function getSourceApi(sourceId: string): Promise<SourceDetail> {
  const { data } = await apiClient.get<SourceDetail>(`/api/v1/sources/${sourceId}`)
  return data
}

export async function getSourceStatsApi(sourceId: string): Promise<SourceStats> {
  const { data } = await apiClient.get<SourceStats>(`/api/v1/sources/${sourceId}/stats`)
  return data
}

export async function listSyncJobsApi(
  sourceId: string,
  limit = 20,
  offset = 0
): Promise<PaginatedSyncJobs> {
  const { data } = await apiClient.get<PaginatedSyncJobs>(`/api/v1/sources/${sourceId}/sync-jobs`, {
    params: { limit, offset },
  })
  return data
}

export async function triggerSyncApi(sourceId: string): Promise<SyncJob> {
  const { data } = await apiClient.post<SyncJob>(`/api/v1/sources/${sourceId}/sync`)
  return data
}

/**
 * U16 — cooperative cancellation of an in-flight sync.
 *
 * The backend sets a Redis flag the running task observes at its next safe
 * checkpoint; work completed up to that point is retained. Returns the
 * updated SyncJob row — for queued jobs this is already `cancelled`; for
 * running jobs the row may still read `running` until the task's next
 * checkpoint (the source-detail polling picks up the transition).
 */
export async function cancelSyncJobApi(sourceId: string, jobId: string): Promise<SyncJob> {
  const { data } = await apiClient.post<SyncJob>(
    `/api/v1/sources/${sourceId}/sync-jobs/${jobId}/cancel`
  )
  return data
}

export async function refreshDescriptionApi(sourceId: string): Promise<RefreshDescriptionResponse> {
  const { data } = await apiClient.post<RefreshDescriptionResponse>(
    `/api/v1/sources/${sourceId}/refresh-description`
  )
  return data
}

export async function autoNameApi(sourceId: string): Promise<AutoNameResponse> {
  const { data } = await apiClient.post<AutoNameResponse>(`/api/v1/sources/${sourceId}/auto-name`)
  return data
}

// ---------------------------------------------------------------------------
// Source intent endpoints (T-023 → consumed by IntentSection via TanStack hooks)
// ---------------------------------------------------------------------------

/**
 * Sentinel thrown by `proposeIntentApi` when the backend returns 409 — a
 * schema study or intent proposal is already in flight for this source. The
 * UI surfaces this as a Sonner toast rather than a generic error.
 *
 * The propose 409 is raised via `HTTPException(detail={...})`, which FastAPI
 * serialises as plain `application/json` (NOT `application/problem+json`), so
 * the shared apiClient interceptor does NOT flatten it — the raw AxiosError
 * (with `response.status === 409`) reaches us here. We still defensively match
 * the backend's stable detail text as a fallback in case a future change
 * routes it through the problem+json normaliser (which drops the status).
 */
export class IntentProposalConflictError extends Error {
  readonly status = 409
  constructor(message = 'A study or proposal is already running.') {
    super(message)
    this.name = 'IntentProposalConflictError'
  }
}

const INTENT_IN_FLIGHT_DETAIL_FRAGMENT = 'already in flight'

export async function getIntentApi(sourceId: string): Promise<SourceIntent> {
  const { data } = await apiClient.get<SourceIntent>(`/api/v1/sources/${sourceId}/intent`)
  return data
}

export async function putIntentApi(
  sourceId: string,
  body: SourceIntentUpdate
): Promise<SourceIntent> {
  const { data } = await apiClient.put<SourceIntent>(`/api/v1/sources/${sourceId}/intent`, body)
  return data
}

/**
 * Enqueue the AI intent-proposal pass (202). Translates the in-flight 409 into
 * a typed `IntentProposalConflictError` so the hook can show a friendly toast.
 */
export async function proposeIntentApi(sourceId: string): Promise<void> {
  try {
    await apiClient.post<void>(`/api/v1/sources/${sourceId}/intent/propose`)
  } catch (error: unknown) {
    const maybeAxios = error as {
      response?: { status?: number }
      status?: number
    }
    const status = maybeAxios.response?.status ?? maybeAxios.status
    if (status === 409) {
      throw new IntentProposalConflictError()
    }
    if (error instanceof Error && error.message.includes(INTENT_IN_FLIGHT_DETAIL_FRAGMENT)) {
      throw new IntentProposalConflictError()
    }
    throw error
  }
}

export async function updateSourceApi(
  sourceId: string,
  body: UpdateSourceRequest
): Promise<SourceDetail> {
  const { data } = await apiClient.patch<SourceDetail>(`/api/v1/sources/${sourceId}`, body)
  return data
}

export async function createSourceApi(body: CreateSourceRequest): Promise<SourceListItem> {
  const { data } = await apiClient.post<SourceListItem>('/api/v1/sources', body)
  return data
}

export async function deleteSourceApi(sourceId: string): Promise<void> {
  await apiClient.delete<void>(`/api/v1/sources/${sourceId}`)
}

export async function testConnectionApi(sourceId: string): Promise<TestConnectionResponse> {
  const { data } = await apiClient.post<TestConnectionResponse>(
    `/api/v1/sources/${sourceId}/test-connection`
  )
  return data
}

// ---------------------------------------------------------------------------
// Edit DB credentials (U8 + FX4)
//
// `PATCH /api/v1/sources/{id}/credentials` accepts a partial credential
// payload plus a `confirm_password` re-auth field. The backend tests the new
// connection BEFORE persisting — a connector-level failure surfaces as 422
// and the source row is left untouched, so the dialog can stay open with the
// connector error.
//
// SECURITY: every field on this body is sensitive. The backend's audit log
// records only the list of CHANGED FIELD NAMES — never the values. UI must
// never log this payload either (no console.log, no analytics emit).
// ---------------------------------------------------------------------------

export interface UpdateSourceCredentialsRequest {
  /**
   * Calling user's own password (FX4 re-auth gate). Backend returns 401 when
   * this does not match the bcrypt hash on the User row.
   */
  confirm_password: string
  /** Optional escape-hatch: full connection URI overrides structured fields. */
  connection_uri?: string
  db_type?: 'postgresql' | 'mysql' | 'mssql' | 'mongodb'
  host?: string
  port?: number
  database?: string
  username?: string
  password?: string
  query?: string
  /**
   * libpq sslmode value — must match the set the backend allows.
   * The backend (`SourceCredentialsUpdateRequest.ssl_mode`) constrains
   * this to a Literal, so widening here keeps the two contracts aligned.
   */
  ssl_mode?: 'disable' | 'require' | 'verify-ca' | 'verify-full'
  collection?: string
}

export async function updateSourceCredentialsApi(
  sourceId: string,
  body: UpdateSourceCredentialsRequest
): Promise<SourceDetail> {
  const { data } = await apiClient.patch<SourceDetail>(
    `/api/v1/sources/${sourceId}/credentials`,
    body
  )
  return data
}

// ---------------------------------------------------------------------------
// Read DB connection config — non-secret pre-fill for the edit dialog (FX7)
//
// `GET /api/v1/sources/{id}/connection-config` returns ONLY the connection
// metadata the admin already typed at creation (db_type / host / port /
// database / username / ssl_mode / collection) plus the SELECT `query` and
// a `has_password` flag. The password and the raw connection string are
// NEVER returned — the dialog pre-fills the visible fields and leaves the
// password input empty (an empty password on submit = "keep current").
// ---------------------------------------------------------------------------

export interface SourceConnectionConfig {
  db_type: 'postgresql' | 'mysql' | 'mssql' | 'mongodb' | null
  host: string | null
  port: number | null
  database: string | null
  username: string | null
  ssl_mode: 'disable' | 'require' | 'verify-ca' | 'verify-full' | null
  collection: string | null
  query: string | null
  /** True iff a password is currently stored — drives the UI placeholder. */
  has_password: boolean
}

export async function getSourceConnectionConfigApi(
  sourceId: string
): Promise<SourceConnectionConfig> {
  const { data } = await apiClient.get<SourceConnectionConfig>(
    `/api/v1/sources/${sourceId}/connection-config`
  )
  return data
}

/**
 * Pre-persistence connection test. Used by the source wizard before any
 * Source row exists — caller passes the typed connection dict directly
 * rather than a stored source id.
 */
export async function inspectSourceApi(body: InspectSourceRequest): Promise<InspectSourceResponse> {
  const { data } = await apiClient.post<InspectSourceResponse>('/api/v1/sources/inspect', body)
  return data
}

export async function listSourceDocumentsApi(
  sourceId: string,
  limit = 50,
  offset = 0
): Promise<PaginatedDocuments> {
  const { data } = await apiClient.get<PaginatedDocuments>(
    `/api/v1/sources/${sourceId}/documents`,
    { params: { limit, offset } }
  )
  return data
}

export async function listSourcePermissionsApi(sourceId: string): Promise<string[]> {
  const { data } = await apiClient.get<SourcePermissionsResponse>(
    `/api/v1/sources/${sourceId}/permissions`
  )
  return data.user_ids
}

export async function grantPermissionApi(sourceId: string, userId: string): Promise<void> {
  await apiClient.post<void>(`/api/v1/sources/${sourceId}/permissions`, {
    user_id: userId,
  } satisfies GrantPermissionRequest)
}

export async function revokePermissionApi(sourceId: string, userId: string): Promise<void> {
  await apiClient.delete<void>(`/api/v1/sources/${sourceId}/permissions/${userId}`)
}

// ---------------------------------------------------------------------------
// SchemaDocument (U7 — admin DB schema viewer)
//
// Mirrors the backend Pydantic models declared in
// `backend/src/services/db_introspection/schema_doc.py` exactly. Fields are
// kept verbatim (snake_case, optional/nullable matching) so the JSON we get
// back does not need a transformer layer.
// ---------------------------------------------------------------------------

export type SchemaDialect = 'postgresql' | 'mysql' | 'mssql' | 'mongodb'

export type TableKind = 'table' | 'view' | 'materialized_view' | 'collection'

export type RelationshipKind = 'foreign_key' | 'embedded_hint'

/** Pipeline phase identifier — string union matches the backend literal. */
export type StudyPhase =
  | 'CONNECTING'
  | 'INVENTORY'
  | 'COLUMNS'
  | 'SAMPLING'
  | 'DESCRIBING'
  | 'INDEXING'

/** One phase-level failure recorded during a partial study. */
export interface PhaseError {
  phase: string
  error_key: string
  message: string
}

export interface IndexDoc {
  name: string
  columns: string[]
  unique: boolean
}

export interface Relationship {
  from_columns: string[]
  to_table: string
  to_columns: string[]
  kind: RelationshipKind
}

export interface ColumnDoc {
  name: string
  /**
   * Normalised column type. The backend allows `array<T>` strings on top of
   * the literal core types — we widen to `string` here to keep the wire
   * shape lossless and let consumers branch on the literals when relevant.
   */
  type: string
  native_type: string
  nullable: boolean
  default: string | null
  sample_values: string[]
  is_pii_candidate: boolean
  inferred: boolean
}

export interface TableDoc {
  name: string
  kind: TableKind
  row_count_estimate: number | null
  primary_key: string[]
  indexes: IndexDoc[]
  columns: ColumnDoc[]
  relationships: Relationship[]
  description: string
  tags: string[]
}

export interface SchemaDocument {
  dialect: SchemaDialect
  fingerprint: string
  generated_at: string
  agent_version: string
  study_duration_ms: number
  partial: boolean
  /**
   * True iff at least one table was skipped or truncated during the study
   * (permission-denied tables, unsafe identifier, source bigger than the
   * per-source cap). Distinct from `partial`: a study can be `partial=true`
   * (e.g. LLM corpus summary failed) without losing coverage.
   *
   * Optional on the wire: documents stored before FX24 default this to
   * `false` on the backend; components must degrade gracefully if it's
   * missing from a stale fixture.
   */
  partial_coverage?: boolean
  /**
   * Qualified names (`schema.table` / `db.collection`) of tables the
   * inspector could not include. Mirrors `phase_errors` but enumerated so
   * the viewer can render a list without parsing messages.
   */
  skipped_tables?: string[]
  /**
   * When set, the source advertised more relations than the per-source
   * cap. The document carries the first N (stable order); `truncated_at`
   * is the full count the source reported.
   */
  truncated_at?: number | null
  /**
   * False iff the DESCRIBING phase produced no usable descriptions (no
   * resolver wired, or every per-table LLM call failed). The viewer
   * surfaces this so missing descriptions aren't confused with a bug.
   */
  llm_descriptions_available?: boolean
  phase_errors: PhaseError[]
  tables: TableDoc[]
  summary: string
  vector_index_ref: string | null
}

export interface SchemaDocumentResponse {
  study_id: string
  state: string
  started_at: string
  finished_at: string | null
  fingerprint_short: string
  schema_document: SchemaDocument
}

/**
 * Sentinel thrown by `getSchemaDocumentApi` when the backend returns 404
 * for a source that has no completed study yet. Carries the HTTP status
 * explicitly so callers (the SchemaViewer empty-state branch) can branch
 * on it without parsing message strings — `parseErrorResponse` flattens
 * RFC-7807 problem-details into a plain `Error` and drops the status.
 */
export class SchemaDocumentNotFoundError extends Error {
  readonly status = 404
  constructor(message = 'Schema not yet documented.') {
    super(message)
    this.name = 'SchemaDocumentNotFoundError'
  }
}

/** Stable detail string the backend emits when no completed study exists. */
const NO_COMPLETED_STUDY_DETAIL = 'No completed schema study for this source.'

export async function getSchemaDocumentApi(sourceId: string): Promise<SchemaDocumentResponse> {
  try {
    const { data } = await apiClient.get<SchemaDocumentResponse>(
      `/api/v1/sources/${sourceId}/schema-document`
    )
    return data
  } catch (error: unknown) {
    // The shared `apiClient` response interceptor flattens RFC-7807
    // problem-details into a plain `Error` and drops the status code.
    // We try two fallbacks before giving up:
    //   1. Inspect axios-like properties in case the interceptor was
    //      bypassed (tests + non-problem+json responses).
    //   2. Match the backend's stable detail text on a plain Error.
    const maybeAxios = error as {
      response?: { status?: number }
      status?: number
    }
    const status = maybeAxios.response?.status ?? maybeAxios.status
    if (status === 404) {
      throw new SchemaDocumentNotFoundError()
    }
    if (error instanceof Error && error.message === NO_COMPLETED_STUDY_DETAIL) {
      throw new SchemaDocumentNotFoundError(error.message)
    }
    throw error
  }
}

/**
 * Audit-emit endpoint called when an admin flips the "Show sample values"
 * toggle ON in the SchemaViewer. Fire-and-forget: we never need the response
 * body and we do NOT call this when the toggle is flipped back to OFF —
 * auditors only care about the moment of reveal.
 */
export async function emitSamplesRevealedApi(sourceId: string): Promise<void> {
  await apiClient.post<void>(`/api/v1/sources/${sourceId}/schema-document/reveal-samples`)
}
