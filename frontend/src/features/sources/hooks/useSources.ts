'use client'

import {
  type CreateSourceRequest,
  type UpdateSourceRequest,
  createSourceApi,
  deleteSourceApi,
  getSourceApi,
  getSourceStatsApi,
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
  syncJobs: (id: string) => [...sourcesKeys.all, 'sync-jobs', id] as const,
}

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

export function useListSources() {
  return useQuery({
    queryKey: sourcesKeys.list(),
    queryFn: () => listSourcesApi(),
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

export function useSyncJobs(sourceId: string | undefined) {
  return useQuery({
    queryKey: sourceId ? sourcesKeys.syncJobs(sourceId) : ['sources', 'sync-jobs', 'empty'],
    queryFn: () => listSyncJobsApi(sourceId as string),
    enabled: Boolean(sourceId),
  })
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useCreateSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateSourceRequest) => createSourceApi(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.all })
      toast.success('Source created successfully')
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error) || 'Failed to create source')
    },
  })
}

export function useUpdateSource(sourceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateSourceRequest) => updateSourceApi(sourceId, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.detail(sourceId) })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.list() })
      toast.success('Source updated')
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error) || 'Failed to update source')
    },
  })
}

export function useDeleteSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sourceId: string) => deleteSourceApi(sourceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: sourcesKeys.all })
      toast.success('Source deleted')
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
      toast.success('Sync started')
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error) || 'Failed to trigger sync')
    },
  })
}

export function useRefreshDescription(sourceId: string) {
  return useMutation({
    mutationFn: () => refreshDescriptionApi(sourceId),
    onSuccess: () => {
      toast.success('Description regenerated — review and save to apply')
    },
    onError: (error: unknown) => {
      toast.error(getErrorMessage(error) || 'Failed to refresh description')
    },
  })
}
