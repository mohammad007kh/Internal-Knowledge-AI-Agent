'use client'

import { apiClient } from '@/lib/api-client'
import { extractApiErrorMessage } from '@/lib/api-error'
import { useMutation, useQueryClient } from '@tanstack/react-query'

/**
 * Wizard-side source type union.
 *
 * Consolidations:
 *   - Files: pdf/docx/xlsx/csv/txt/markdown → ``file_upload`` (single Files
 *     card with multi-file upload).
 *   - Databases: postgresql/mysql/mssql/mongodb → ``database`` (single
 *     Database card; the specific dialect lives in the connection payload
 *     as ``db_type``).
 *
 * See: POST /api/v1/sources
 */
export type WizardSourceType = 'database' | 'file_upload' | 'web_url' | 'confluence' | 'sharepoint'

export type FileTypeKey = 'pdf' | 'docx' | 'xlsx' | 'csv' | 'txt' | 'markdown'

export type SyncMode = 'manual' | 'scheduled' | 'delta'
export type RetrievalMode = 'vector_only' | 'text_to_query' | 'hybrid'

/**
 * One uploaded file inside a consolidated ``file_upload`` source.
 *
 * The shape mirrors the backend ``FileRef`` schema in
 * ``backend/src/schemas/source.py``.
 */
export interface UploadedFileRef {
  object_key: string
  original_name: string
  file_type: FileTypeKey
  size_bytes: number | null
}

export interface CreateSourcePayload {
  name: string
  source_type: WizardSourceType
  connection: Record<string, unknown> | null
  /**
   * Multi-file payload for ``source_type === 'file_upload'``.  Empty/null
   * for non-file source types.
   */
  files: UploadedFileRef[] | null
  description: string
  sync_mode: SyncMode
  sync_schedule: string | null
  retrieval_mode: RetrievalMode
  citations_enabled: boolean
  /**
   * Embedder pinned to this source. Defaults server-side to the currently
   * active embedder when omitted (per design doc §7). v1 sources are locked
   * to the active embedder — the UI surfaces this as read-only.
   */
  embedder_id?: string | null
  /**
   * When true, the backend stamps a placeholder name + description on the
   * row and schedules an AI-naming pass to rewrite both after first
   * ingestion. The form submits an empty `name` / `description` alongside
   * this flag — the server is the source of truth for the placeholder.
   */
  auto_name_and_description?: boolean
}

export interface CreatedSource {
  id: string
  name: string
  source_type: WizardSourceType
  source_mode: 'snapshot' | 'live'
  retrieval_mode: RetrievalMode
  description: string
  sync_mode: SyncMode
  sync_schedule: string | null
  last_synced_at: string | null
  status: string
  citations_enabled: boolean
  created_at: string
  updated_at: string
}

async function createSource(payload: CreateSourcePayload): Promise<CreatedSource> {
  try {
    const { data } = await apiClient.post<CreatedSource>('/api/v1/sources', payload)
    return data
  } catch (error: unknown) {
    // Surface the backend's RFC-7807 `detail` (incl. the nested
    // `detail.detail` shape FastAPI emits for `HTTPException(detail={...})`)
    // rather than axios's generic "Request failed with status code …".
    throw new Error(extractApiErrorMessage(error))
  }
}

/**
 * Mutation hook for the source wizard. Invalidates ['sources'] on success so
 * the sources list page refreshes automatically on navigation.
 */
export function useCreateSource() {
  const queryClient = useQueryClient()
  return useMutation<CreatedSource, Error, CreateSourcePayload>({
    mutationFn: createSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
    },
  })
}
