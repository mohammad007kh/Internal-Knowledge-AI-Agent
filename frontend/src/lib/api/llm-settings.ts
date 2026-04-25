import { apiClient, parseErrorResponse } from '@/lib/api-client'
import type { AIModelCapabilities } from '@/types/ai-model'

/**
 * Pipeline stage slug. Source of truth: backend
 * `src/api/v1/admin/llm_settings.py` `STAGES` list (10 entries).
 */
export type LlmStage =
  | 'schema_inspector'
  | 'clarification_detector'
  | 'query_analyzer'
  | 'source_router'
  | 'retrieval'
  | 'text_to_query'
  | 'synthesizer'
  | 'reflector'
  | 'input_guard'
  | 'output_guard'

/**
 * Lightweight `ai_model` block returned for each stage post-rewire (design
 * doc §7). The full record is fetched separately when needed.
 */
export interface LlmStageAiModel {
  id: string
  name: string
  provider: string
  model_id: string
  capabilities: AIModelCapabilities
}

export interface LlmStageConfig {
  stage: LlmStage
  label: string
  description: string
  /** Linked AI Model record after rewire. ``null`` while the table is empty. */
  ai_model: LlmStageAiModel | null
  /**
   * Legacy fields retained for backward compatibility while PR 2 ships the
   * pipeline rewire. UI prefers `ai_model` when present.
   */
  model: string
  api_key_hint: string | null
  temperature: number
  max_tokens: number
  custom_prompt: string | null
}

/**
 * Post-rewire body — references an AI Model record by id. The legacy
 * `model` / `api_key` fields are accepted by the backend during the
 * transition (PR 2), but the frontend always uses `ai_model_id` going
 * forward.
 */
export interface UpdateLlmStageRequest {
  ai_model_id: string
  temperature?: number
  max_tokens?: number
  custom_prompt?: string | null
}

export interface TestLlmStageResponse {
  success: boolean
  latency_ms: number | null
  error?: string | null
}

export async function listLlmSettingsApi(): Promise<LlmStageConfig[]> {
  try {
    const { data } = await apiClient.get<LlmStageConfig[]>('/api/v1/admin/llm-settings')
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

export async function updateLlmStageApi(
  stage: LlmStage,
  body: UpdateLlmStageRequest
): Promise<LlmStageConfig> {
  try {
    const { data } = await apiClient.put<LlmStageConfig>(
      `/api/v1/admin/llm-settings/${stage}`,
      body
    )
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

export async function testLlmStageApi(stage: LlmStage): Promise<TestLlmStageResponse> {
  try {
    const { data } = await apiClient.post<TestLlmStageResponse>(
      `/api/v1/admin/llm-settings/${stage}/test`
    )
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}
