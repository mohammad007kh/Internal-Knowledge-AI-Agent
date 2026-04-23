import { apiClient } from '@/lib/api-client'

export type LlmStage =
  | 'query_rewriter'
  | 'retriever'
  | 'reranker'
  | 'context_builder'
  | 'answer_generator'
  | 'citation_formatter'
  | 'clarification_handler'
  | 'guardrail_input'
  | 'guardrail_output'
  | 'schema_inspector'

export interface LlmStageConfig {
  stage: LlmStage
  label: string
  description: string
  model: string
  api_key_hint: string | null
  temperature: number
  max_tokens: number
  custom_prompt: string | null
}

export interface UpdateLlmStageRequest {
  model: string
  api_key?: string
  temperature: number
  max_tokens: number
  custom_prompt?: string | null
}

export interface TestLlmStageResponse {
  success: boolean
  latency_ms: number | null
  error?: string | null
}

export async function listLlmSettingsApi(): Promise<LlmStageConfig[]> {
  const { data } = await apiClient.get<LlmStageConfig[]>('/api/v1/admin/llm-settings')
  return data
}

export async function updateLlmStageApi(
  stage: LlmStage,
  body: UpdateLlmStageRequest
): Promise<LlmStageConfig> {
  const { data } = await apiClient.put<LlmStageConfig>(
    `/api/v1/admin/llm-settings/${stage}`,
    body
  )
  return data
}

export async function testLlmStageApi(stage: LlmStage): Promise<TestLlmStageResponse> {
  const { data } = await apiClient.post<TestLlmStageResponse>(
    `/api/v1/admin/llm-settings/${stage}/test`
  )
  return data
}
