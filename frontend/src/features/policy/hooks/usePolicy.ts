'use client'

import {
  type GuardrailEventFilters,
  type UpdatePolicyRequest,
  getGuardrailEventApi,
  getPolicyApi,
  listGuardrailEventsApi,
  updatePolicyApi,
} from '@/lib/api/policy'
import { getErrorMessage } from '@/lib/errors'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

const POLICY_KEY = ['admin', 'policy'] as const
const GUARDRAIL_EVENTS_KEY = ['admin', 'guardrail-events'] as const

export function usePolicy() {
  return useQuery({
    queryKey: POLICY_KEY,
    queryFn: getPolicyApi,
  })
}

export function useUpdatePolicy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdatePolicyRequest) => updatePolicyApi(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: POLICY_KEY })
      toast.success('Policy updated')
    },
    onError: (error) => {
      toast.error(getErrorMessage(error))
    },
  })
}

export function useGuardrailEvents(filters: GuardrailEventFilters) {
  return useQuery({
    queryKey: [...GUARDRAIL_EVENTS_KEY, filters],
    queryFn: () => listGuardrailEventsApi(filters),
  })
}

export function useGuardrailEvent(eventId: string | null) {
  return useQuery({
    queryKey: [...GUARDRAIL_EVENTS_KEY, 'detail', eventId],
    queryFn: () => {
      if (!eventId) throw new Error('eventId is required')
      return getGuardrailEventApi(eventId)
    },
    enabled: !!eventId,
  })
}
