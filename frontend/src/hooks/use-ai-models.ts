'use client'

import { apiClient, parseErrorResponse } from '@/lib/api-client'
import type {
  AIModelCreateRequest,
  AIModelListResponse,
  AIModelPublic,
  AIModelTestPlaintextRequest,
  AIModelUpdateRequest,
  AIModelUsage,
  TestConnectionResponse,
} from '@/types/ai-model'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

/**
 * Data hooks for `/api/v1/admin/ai-models` — see
 * docs/ai-models-and-embedders-design.md §7.
 */

const AI_MODELS_KEY = ['admin', 'ai-models'] as const
const aiModelKey = (id: string) => [...AI_MODELS_KEY, id] as const
const aiModelUsageKey = (id: string) => [...aiModelKey(id), 'usage'] as const

export interface AiModelsListParams {
  q?: string
  provider?: string
  active?: boolean
  limit?: number
  offset?: number
}

async function listAiModels(params: AiModelsListParams): Promise<AIModelListResponse> {
  try {
    const { data } = await apiClient.get<AIModelListResponse>('/api/v1/admin/ai-models', {
      params,
    })
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function getAiModel(id: string): Promise<AIModelPublic> {
  try {
    const { data } = await apiClient.get<AIModelPublic>(`/api/v1/admin/ai-models/${id}`)
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function createAiModel(body: AIModelCreateRequest): Promise<AIModelPublic> {
  try {
    const { data } = await apiClient.post<AIModelPublic>('/api/v1/admin/ai-models', body)
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function updateAiModel(id: string, body: AIModelUpdateRequest): Promise<AIModelPublic> {
  try {
    const { data } = await apiClient.patch<AIModelPublic>(`/api/v1/admin/ai-models/${id}`, body)
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function deleteAiModel(id: string): Promise<void> {
  try {
    await apiClient.delete<void>(`/api/v1/admin/ai-models/${id}`)
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function testAiModelPlaintext(
  body: AIModelTestPlaintextRequest
): Promise<TestConnectionResponse> {
  try {
    const { data } = await apiClient.post<TestConnectionResponse>(
      '/api/v1/admin/ai-models/test-connection',
      body
    )
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function testAiModelById(id: string): Promise<TestConnectionResponse> {
  try {
    const { data } = await apiClient.post<TestConnectionResponse>(
      `/api/v1/admin/ai-models/${id}/test-connection`
    )
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

async function getAiModelUsage(id: string): Promise<AIModelUsage> {
  try {
    const { data } = await apiClient.get<AIModelUsage>(`/api/v1/admin/ai-models/${id}/usage`)
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

export function useAiModels(params: AiModelsListParams = {}) {
  return useQuery({
    queryKey: [...AI_MODELS_KEY, params],
    queryFn: () => listAiModels(params),
    placeholderData: (prev) => prev,
    // Picker reopens shouldn't trigger a fresh round-trip every time. The
    // list is short and admin-only, so 30s is a safe staleness budget.
    staleTime: 30_000,
  })
}

export function useAiModel(id: string | null | undefined) {
  return useQuery({
    queryKey: id ? aiModelKey(id) : [...AI_MODELS_KEY, 'noop'],
    queryFn: () => {
      if (!id) throw new Error('useAiModel called without id')
      return getAiModel(id)
    },
    enabled: Boolean(id),
  })
}

export function useCreateAiModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: createAiModel,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: AI_MODELS_KEY })
    },
  })
}

export function useUpdateAiModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: AIModelUpdateRequest }) =>
      updateAiModel(id, body),
    onSuccess: (_data, variables) => {
      qc.invalidateQueries({ queryKey: AI_MODELS_KEY })
      qc.invalidateQueries({ queryKey: aiModelKey(variables.id) })
    },
  })
}

export function useDeleteAiModel() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: deleteAiModel,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: AI_MODELS_KEY })
    },
  })
}

/**
 * Test connection from the create/edit form (plaintext key, not yet saved).
 * Backend never persists the supplied key.
 */
export function useTestAiModelConnection() {
  return useMutation({
    mutationFn: testAiModelPlaintext,
  })
}

/**
 * Test connection on a stored AI Model record. Updates `last_test_at` /
 * `last_test_status` server-side.
 */
export function useTestAiModelConnectionById() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: testAiModelById,
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: aiModelKey(id) })
      qc.invalidateQueries({ queryKey: AI_MODELS_KEY })
    },
  })
}

export interface UseAiModelUsageOptions {
  /**
   * Override the auto-derived `enabled` flag. The hook still requires a
   * truthy `id`; this option lets callers add additional gating (e.g. only
   * fetch while a confirmation dialog is open).
   */
  enabled?: boolean
}

export function useAiModelUsage(
  id: string | null | undefined,
  options: UseAiModelUsageOptions = {}
) {
  const { enabled = true } = options
  return useQuery({
    queryKey: id ? aiModelUsageKey(id) : [...AI_MODELS_KEY, 'usage', 'noop'],
    queryFn: () => {
      if (!id) throw new Error('useAiModelUsage called without id')
      return getAiModelUsage(id)
    },
    enabled: Boolean(id) && enabled,
  })
}
