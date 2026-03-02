'use client'

import { apiClient } from '@/lib/api-client'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import type { SourceSummary } from './SourceSelector'

interface UseSessionSourcesOptions {
  sessionId: string | null
}

interface SessionResponse {
  session: { id: string; source_ids: string[] }
  messages: unknown[]
}

async function fetchSession(id: string): Promise<SessionResponse> {
  const res = await apiClient.get<SessionResponse>(`/chat/sessions/${id}`)
  return res.data
}

async function updateSessionSources(id: string, sourceIds: string[]): Promise<void> {
  await apiClient.patch(`/chat/sessions/${id}`, { source_ids: sourceIds })
}

async function fetchSourcesByIds(ids: string[]): Promise<SourceSummary[]> {
  if (ids.length === 0) return []
  const qs = ids.map((id) => `ids=${id}`).join('&')
  const res = await apiClient.get<{ items: SourceSummary[] }>(`/sources?${qs}&limit=${ids.length}`)
  return res.data.items
}

export function useSessionSources({ sessionId }: UseSessionSourcesOptions) {
  const queryClient = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [selectedSources, setSelectedSources] = useState<SourceSummary[]>([])

  const { data: sessionData } = useQuery({
    queryKey: ['chat-session-messages', sessionId],
    queryFn: () => fetchSession(sessionId ?? ''),
    enabled: !!sessionId,
    staleTime: 10_000,
  })

  const sourceIds = sessionData?.session.source_ids

  useEffect(() => {
    const ids = sourceIds ?? []
    setSelectedIds(ids)
  }, [sourceIds])

  useEffect(() => {
    if (selectedIds.length === 0) {
      setSelectedSources([])
      return
    }
    fetchSourcesByIds(selectedIds)
      .then(setSelectedSources)
      .catch(() => setSelectedSources([]))
  }, [selectedIds])

  const updateMutation = useMutation({
    mutationFn: (ids: string[]) => updateSessionSources(sessionId ?? '', ids),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['chat-session-messages', sessionId] })
    },
    onError: () => toast.error('Failed to update sources.'),
  })

  const handleChange = useCallback(
    (ids: string[]) => {
      setSelectedIds(ids)
      if (sessionId) updateMutation.mutate(ids)
    },
    [sessionId, updateMutation]
  )

  const handleRemove = useCallback(
    (id: string) => {
      handleChange(selectedIds.filter((x) => x !== id))
    },
    [handleChange, selectedIds]
  )

  return {
    selectedIds,
    selectedSources,
    handleChange,
    handleRemove,
    isUpdating: updateMutation.isPending,
  }
}
