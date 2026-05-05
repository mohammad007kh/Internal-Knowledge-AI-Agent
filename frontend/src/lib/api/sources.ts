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
  // is_active = "approved/available to users". New sources default to false
  // — admin must explicitly approve via PATCH.
  is_active: boolean
  // Soft-delete marker. The list endpoint never returns soft-deleted rows;
  // this field is kept for completeness when a single source is fetched.
  deleted_at?: string | null
  name: string
  source_type: SourceType
  created_at: string
  // Phase-2 enriched fields (optional for backwards compatibility)
  source_mode?: SourceMode
  status?: SourceStatus | null
  sync_mode?: SyncMode | null
  last_synced_at?: string | null
  description?: string | null
  latest_job?: SyncJob | null
  // Ingestion-clarity fields (T-107). Populated server-side; defaulted to
  // 0 / false on rows that pre-date the schema.  Drive the four-stage
  // strip on /admin/sources (Uploaded / Parsed / Chunked / Approved).
  document_count?: number
  chunk_count?: number
  has_upload?: boolean
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

interface ListSourcesOptions {
  limit?: number
  offset?: number
  // When true, filter to admin-approved sources only (is_active=true).
  // Use this from user-facing surfaces (e.g. the chat session source picker).
  // Admin sources list omits this so pending-approval rows remain visible.
  availableOnly?: boolean
}

export async function listSourcesApi(
  limitOrOptions: number | ListSourcesOptions = 50,
  offset = 0
): Promise<PaginatedSources> {
  const opts: Required<ListSourcesOptions> =
    typeof limitOrOptions === 'number'
      ? { limit: limitOrOptions, offset, availableOnly: false }
      : {
          limit: limitOrOptions.limit ?? 50,
          offset: limitOrOptions.offset ?? 0,
          availableOnly: limitOrOptions.availableOnly ?? false,
        }

  const params: Record<string, string | number> = {
    limit: opts.limit,
    offset: opts.offset,
  }
  if (opts.availableOnly) {
    params.available_only = 'true'
  }
  const { data } = await apiClient.get<PaginatedSources>('/api/v1/sources', {
    params,
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
