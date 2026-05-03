'use client'

import { apiClient, parseErrorResponse } from '@/lib/api-client'
import type { TestConnectionResponse } from '@/types/ai-model'
import type {
  ActivateEmbedderPreview,
  ActivateEmbedderResponse,
  EmbedderCreateRequest,
  EmbedderListResponse,
  EmbedderPublic,
  EmbedderTestPlaintextRequest,
  EmbedderUpdateRequest,
} from '@/types/embedder'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

/**
 * Data hooks for `/api/v1/admin/embedders` — see
 * docs/ai-models-and-embedders-design.md §7.
 *
 * v1 invariant: at most one active embedder. Activating another triggers a
 * Celery re-embed job. Use `useActivateEmbedderPreview` to dry-run first.
 */

const EMBEDDERS_KEY = ['admin', 'embedders'] as const
const embedderKey = (id: string) => [...EMBEDDERS_KEY, id] as const
const previewKey = (id: string) => [...embedderKey(id), 'activate-preview'] as const

export interface EmbeddersListParams {
  q?: string
  provider?: string
  active?: boolean
  limit?: number
  offset?: number
}

async function listEmbedders(params: EmbeddersListParams): Promise<EmbedderListResponse> {
  try {
    const { data } = await apiClient.get<EmbedderListResponse>('/api/v1/admin/embedders', {
      params,
    })
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function getEmbedder(id: string): Promise<EmbedderPublic> {
  try {
    const { data } = await apiClient.get<EmbedderPublic>(`/api/v1/admin/embedders/${id}`)
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function createEmbedder(body: EmbedderCreateRequest): Promise<EmbedderPublic> {
  try {
    const { data } = await apiClient.post<EmbedderPublic>('/api/v1/admin/embedders', body)
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function updateEmbedder(id: string, body: EmbedderUpdateRequest): Promise<EmbedderPublic> {
  try {
    const { data } = await apiClient.patch<EmbedderPublic>(`/api/v1/admin/embedders/${id}`, body)
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function deleteEmbedder(id: string): Promise<void> {
  try {
    await apiClient.delete<void>(`/api/v1/admin/embedders/${id}`)
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function testEmbedderPlaintext(
  body: EmbedderTestPlaintextRequest
): Promise<TestConnectionResponse> {
  try {
    const { data } = await apiClient.post<TestConnectionResponse>(
      '/api/v1/admin/embedders/test-connection',
      body
    )
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function testEmbedderById(id: string): Promise<TestConnectionResponse> {
  try {
    const { data } = await apiClient.post<TestConnectionResponse>(
      `/api/v1/admin/embedders/${id}/test-connection`
    )
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function getActivatePreview(id: string): Promise<ActivateEmbedderPreview> {
  try {
    const { data } = await apiClient.get<ActivateEmbedderPreview>(
      `/api/v1/admin/embedders/${id}/activate-preview`
    )
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function activateEmbedder(id: string): Promise<ActivateEmbedderResponse> {
  try {
    const { data } = await apiClient.post<ActivateEmbedderResponse>(
      `/api/v1/admin/embedders/${id}/activate`
    )
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

/**
 * List query for the embedders admin page.
 *
 * `placeholderData: (prev) => prev` keeps the previous page on screen while a
 * search refines, and `select` normalises the response so `data.items` and
 * `data.total` are always defined — defending consumers from a backend that
 * ships a partial payload (see /admin/embedders crash regression).
 */
export function useEmbedders(params: EmbeddersListParams = {}) {
  return useQuery<EmbedderListResponse, Error, EmbedderListResponse>({
    queryKey: [...EMBEDDERS_KEY, params],
    queryFn: () => listEmbedders(params),
    placeholderData: (prev) => prev,
    select: (raw): EmbedderListResponse => ({
      items: raw?.items ?? [],
      total: raw?.total ?? 0,
      limit: raw?.limit ?? params.limit ?? 0,
      offset: raw?.offset ?? params.offset ?? 0,
    }),
  })
}

export function useEmbedder(id: string | null | undefined) {
  return useQuery({
    queryKey: id ? embedderKey(id) : [...EMBEDDERS_KEY, 'noop'],
    queryFn: () => {
      if (!id) throw new Error('useEmbedder called without id')
      return getEmbedder(id)
    },
    enabled: Boolean(id),
  })
}

export function useCreateEmbedder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: createEmbedder,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: EMBEDDERS_KEY })
    },
  })
}

export function useUpdateEmbedder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: EmbedderUpdateRequest }) =>
      updateEmbedder(id, body),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: EMBEDDERS_KEY })
      qc.invalidateQueries({ queryKey: embedderKey(variables.id) })
    },
  })
}

export function useDeleteEmbedder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteEmbedder,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: EMBEDDERS_KEY })
    },
  })
}

export function useTestEmbedderConnection() {
  return useMutation({
    mutationFn: testEmbedderPlaintext,
  })
}

export function useTestEmbedderConnectionById() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: testEmbedderById,
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: embedderKey(id) })
      qc.invalidateQueries({ queryKey: EMBEDDERS_KEY })
    },
  })
}

/**
 * Dry-run preview of an activation. Cheap on the backend (single COUNT +
 * per-provider rate constant). Does not change state.
 */
export function useActivateEmbedderPreview(id: string | null | undefined) {
  return useQuery({
    queryKey: id ? previewKey(id) : [...EMBEDDERS_KEY, 'preview', 'noop'],
    queryFn: () => {
      if (!id) throw new Error('useActivateEmbedderPreview called without id')
      return getActivatePreview(id)
    },
    enabled: Boolean(id),
    staleTime: 30 * 1000,
  })
}

export function useActivateEmbedder() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: activateEmbedder,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: EMBEDDERS_KEY })
    },
  })
}
