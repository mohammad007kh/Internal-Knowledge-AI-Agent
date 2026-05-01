import { apiClient } from '@/lib/api-client'

export interface Policy {
  id: string
  content: string
  created_at: string
}

export interface UpdatePolicyRequest {
  content: string
}

export type GuardrailType = 'input' | 'output'
export type GuardrailAction = 'blocked' | 'logged'

export interface GuardrailEvent {
  id: string
  guard_type: GuardrailType
  action: GuardrailAction
  original_input: string
  created_at: string
}

export interface GuardrailEventDetail extends GuardrailEvent {
  // Backend returns the full record; kept open for additional diagnostic fields
  [key: string]: unknown
}

export interface PaginatedGuardrailEvents {
  items: GuardrailEvent[]
  total: number
  limit: number
  offset: number
}

export interface GuardrailEventFilters {
  limit?: number
  offset?: number
  guard_type?: GuardrailType
  action?: GuardrailAction
}

export async function getPolicyApi(): Promise<Policy> {
  const { data } = await apiClient.get<Policy>('/api/v1/admin/policy')
  return data
}

export async function updatePolicyApi(body: UpdatePolicyRequest): Promise<Policy> {
  const { data } = await apiClient.put<Policy>('/api/v1/admin/policy', body)
  return data
}

export async function listGuardrailEventsApi(
  filters: GuardrailEventFilters = {}
): Promise<PaginatedGuardrailEvents> {
  const params: Record<string, string | number> = {
    limit: filters.limit ?? 20,
    offset: filters.offset ?? 0,
  }
  if (filters.guard_type) params.guard_type = filters.guard_type
  if (filters.action) params.action = filters.action

  const { data } = await apiClient.get<PaginatedGuardrailEvents>(
    '/api/v1/admin/guardrail-events',
    { params }
  )
  return data
}

export async function getGuardrailEventApi(eventId: string): Promise<GuardrailEventDetail> {
  const { data } = await apiClient.get<GuardrailEventDetail>(
    `/api/v1/admin/guardrail-events/${eventId}`
  )
  return data
}
