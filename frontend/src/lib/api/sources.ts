import { apiClient } from '@/lib/api-client'

// ---------------------------------------------------------------------------
// Source domain types
// ---------------------------------------------------------------------------

export type SourceType =
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
  | 'web_url'
  | 'file_upload'

export type SourceStatus = 'pending' | 'syncing' | 'ready' | 'error' | 'disabled'
export type SyncMode = 'manual' | 'scheduled' | 'delta'
export type SourceMode = 'snapshot' | 'live'
export type RetrievalMode = 'vector_only' | 'text_to_query' | 'hybrid'

// ---------------------------------------------------------------------------
// DB-source studying agent (Wave 1A schema columns)
//
// These fields ship in the database in Wave 1A and are exposed on the
// `SourceListItem` payload in Wave 3 once the studying agent is merged. They
// are *optional* on the wire today — components must degrade gracefully when
// the API has not yet populated them.
// ---------------------------------------------------------------------------

export type SchemaStatus = 'QUEUED' | 'STUDYING' | 'READY' | 'STALE' | 'FAILED'

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
  status: 'pending' | 'running' | 'completed' | 'failed' | 'success'
  started_at: string | null
  finished_at: string | null
  completed_at: string | null
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
}

export interface UpdateSourceRequest {
  name?: string
  description?: string | null
  citations_enabled?: boolean
  is_active?: boolean
}

export interface TestConnectionResponse {
  success: boolean
  message: string
}

export interface RefreshDescriptionResponse {
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

export async function refreshDescriptionApi(sourceId: string): Promise<RefreshDescriptionResponse> {
  const { data } = await apiClient.post<RefreshDescriptionResponse>(
    `/api/v1/sources/${sourceId}/refresh-description`
  )
  return data
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
