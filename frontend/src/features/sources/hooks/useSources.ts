'use client'

import {
  type UpdateSourceRequest,
  autoNameApi,
  deleteSourceApi,
  getSourceApi,
  getSourceStatsApi,
  listSourceDocumentsApi,
  listSourcesApi,
  listSyncJobsApi,
  refreshDescriptionApi,
  testConnectionApi,
  triggerSyncApi,
  updateSourceApi,
} from '@/lib/api/sources'
import { getErrorMessage } from '@/lib/errors'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

// ---------------------------------------------------------------------------
// Query key factory — single source of truth
// ---------------------------------------------------------------------------

export const sourcesKeys = {
  all: ['sources'] as const,
  list: () => [...sourcesKeys.all, 'list'] as const,
  detail: (id: string) => [...sourcesKeys.all, 'detail', id] as const,
  stats: (id: string) => [...sourcesKeys.all, 'stats', id] as const,
  // Sync jobs are paginated — the key includes limit/offset so each page is
  // cached independently and Previous/Next don't blow away other pages.
  syncJobs: (id: string, limit?: number, offset?: number) =>
    limit === undefined && offset === undefined
      ? ([...sourcesKeys.all, 'sync-jobs', id] as const)
      : ([...sourcesKeys.all, 'sync-jobs', id, { limit, offset }] as const),
  documents: (id: string) => [...sourcesKeys.all, 'documents', id] as const,
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export interface UseListSourcesOptions {
  /**
   * When `true`, refetch every 5 seconds. Callers should set this when any
   * visible row is in the `running` phase so the verb column transitions out
   * of "Working on it…" promptly. When `false` (default), the query stays on
   * the React Query default (no polling, refetch on focus).
   */
  pollWhileRunning?: boolean
}

export function useListSources(options: UseListSourcesOptions = {}) {
  const { pollWhileRunning = false } = options
  return useQuery({
    queryKey: sourcesKeys.list(),
    queryFn: () => listSourcesApi(),
    refetchInterval: pollWhileRunning ? 5_000 : false,
  })
}

export function useSource(sourceId: string | undefined) {
  return useQuery({
    queryKey: sourceId ? sourcesKeys.detail(sourceId) : ['sources', 'detail', 'empty'],
    queryFn: () => getSourceApi(sourceId as string),
    enabled: Boolean(sourceId),
  })
}

export function useSourceStats(sourceId: string | undefined) {
  return useQuery({
    queryKey: sourceId ? sourcesKeys.stats(sourceId) : ['sources', 'stats', 'empty'],
    queryFn: () => getSourceStatsApi(sourceId as string),
    enabled: Boolean(sourceId),
  })
}

export interface UseSyncJobsOptions {
  limit?: number
  offset?: number
}

/**
 * Paginated sync-jobs query. `limit` defaults to the API's default (20) and
 * `offset` to 0. Each (sourceId, limit, offset) tuple is cached independently
 * — Previous/Next on the detail page reuse cached pages instantly.
 *
 * Backwards compatible with the previous `useSyncJobs(id)` call site: omit the
 * options object and the hook keeps the original behavior.
 */
export function useSyncJobs(sourceId: string | undefined, options: UseSyncJobsOptions = {}) {
  const { limit, offset } = options
  return useQuery({
    queryKey: sourceId
      ? sourcesKeys.syncJobs(sourceId, limit, offset)
      : ['sources', 'sync-jobs', 'empty'],
    queryFn: () => listSyncJobsApi(sourceId as string, limit, offset),
    enabled: Boolean(sourceId),
  })
}

export function useSourceDocuments(sourceId: string | undefined) {
  return useQuery({
    queryKey: sourceId ? sourcesKeys.documents(sourceId) : ['sources', 'documents', 'empty'],
    queryFn: () => listSourceDocumentsApi(sourceId as string),
    enabled: Boolean(sourceId),
  })
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useUpdateSource(sourceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateSourceRequest) => updateSourceApi(sourceId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.detail(sourceId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.list() })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
    },
  })
}

export function useDeleteSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sourceId: string) => deleteSourceApi(sourceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.all })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
      toast.success('Source deleted.')
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error) || 'Failed to delete source')
    },
  })
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (sourceId: string) => testConnectionApi(sourceId),
    onSuccess: (data) => {
      if (data.success) {
        toast.success(data.message || 'Connection successful')
      } else {
        toast.error(data.message || 'Connection failed')
      }
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error) || 'Connection test failed')
    },
  })
}

export function useTriggerSync() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sourceId: string) => triggerSyncApi(sourceId),
    onSuccess: (_data, sourceId) => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.list() })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.detail(sourceId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.syncJobs(sourceId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.stats(sourceId) })
    },
  })
}

export function useRefreshDescription(sourceId: string) {
  return useMutation({
    mutationFn: () => refreshDescriptionApi(sourceId),
  })
}

export function useAutoNameSource(sourceId: string) {
  return useMutation({
    mutationFn: () => autoNameApi(sourceId),
  })
}
