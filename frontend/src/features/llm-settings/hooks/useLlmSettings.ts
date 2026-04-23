'use client'

import {
  type LlmStage,
  type UpdateLlmStageRequest,
  listLlmSettingsApi,
  testLlmStageApi,
  updateLlmStageApi,
} from '@/lib/api/llm-settings'
import { getErrorMessage } from '@/lib/errors'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

const LLM_SETTINGS_KEY = ['admin', 'llm-settings'] as const

export function useLlmSettings() {
  return useQuery({
    queryKey: LLM_SETTINGS_KEY,
    queryFn: listLlmSettingsApi,
  })
}

export function useUpdateLlmStage() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ stage, body }: { stage: LlmStage; body: UpdateLlmStageRequest }) =>
      updateLlmStageApi(stage, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: LLM_SETTINGS_KEY })
      toast.success('LLM settings saved')
    },
    onError: (error) => {
      toast.error(getErrorMessage(error))
    },
  })
}

export function useTestLlmStage() {
  return useMutation({
    mutationFn: (stage: LlmStage) => testLlmStageApi(stage),
  })
}
