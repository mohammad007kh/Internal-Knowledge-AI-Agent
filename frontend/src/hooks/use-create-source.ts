'use client'

import { apiClient, parseErrorResponse } from '@/lib/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'

/**
 * Full source type set for T-006 wizard (superset of the legacy 4-type dialog).
 * See: POST /api/v1/sources
 */
export type WizardSourceType =
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
  | 'confluence'
  | 'sharepoint'

export type SyncMode = 'manual' | 'scheduled' | 'delta'
export type RetrievalMode = 'vector_only' | 'text_to_query' | 'hybrid'

export interface CreateSourcePayload {
  name: string
  source_type: WizardSourceType
  connection: Record<string, unknown> | null
  object_key: string | null
  description: string
  sync_mode: SyncMode
  sync_schedule: string | null
  retrieval_mode: RetrievalMode
  citations_enabled: boolean
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
    throw parseErrorResponse(error)
  }
}

/**
 * Mutation hook for T-006 wizard. Invalidates ['sources'] on success so the
 * sources list page refreshes automatically on navigation.
 */
export function useCreateSource() {
  const queryClient = useQueryClient()
  return useMutation<CreatedSource, Error, CreateSourcePayload>({
    mutationFn: createSource,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sources'] })
    },
  })
}
