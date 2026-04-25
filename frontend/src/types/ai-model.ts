/**
 * AI Model resource types — mirrors `/api/v1/admin/ai-models` shapes from
 * docs/ai-models-and-embedders-design.md §3 + §7.
 *
 * Security invariants enforced by the API:
 *  - GET endpoints never return plaintext API keys; only `api_key_last4` and `api_key_set`.
 *  - PATCH preserves the existing key when `api_key` is omitted/null.
 */

export type TestConnectionStatus = 'ok' | 'failed' | 'never'

export interface AIModelCapabilities {
  function_calling?: boolean
  vision?: boolean
  json_mode?: boolean
  streaming?: boolean
  max_context_tokens?: number
  /** USD per 1M input tokens — used for sort ordering in pickers. */
  input_cost_per_1m?: number
  /** USD per 1M output tokens. */
  output_cost_per_1m?: number
}

export interface AIModelPublic {
  id: string
  name: string
  provider: string
  base_url: string | null
  model_id: string
  /** Last 4 chars of the encrypted API key, for masked display. */
  api_key_last4: string | null
  api_key_set: boolean
  extra_config: Record<string, unknown>
  default_temperature: number
  default_max_tokens: number
  capabilities: AIModelCapabilities
  is_active: boolean
  last_test_at: string | null
  last_test_status: TestConnectionStatus
  last_test_error: string | null
  created_at: string
  updated_at: string
  created_by: string | null
}

export interface AIModelListResponse {
  items: readonly AIModelPublic[]
  total: number
  limit: number
  offset: number
}

export interface AIModelCreateRequest {
  name: string
  provider: string
  model_id: string
  api_key: string
  base_url?: string | null
  extra_config?: Record<string, unknown>
  default_temperature?: number
  default_max_tokens?: number
  capabilities?: AIModelCapabilities
  is_active?: boolean
}

export interface AIModelUpdateRequest {
  name?: string
  provider?: string
  model_id?: string
  /** Omit/null to preserve existing key. */
  api_key?: string | null
  base_url?: string | null
  extra_config?: Record<string, unknown>
  default_temperature?: number
  default_max_tokens?: number
  capabilities?: AIModelCapabilities
  is_active?: boolean
}

/**
 * Plaintext form-driven test (`POST /test-connection`). Works pre-save and
 * never persists the supplied key.
 */
export interface AIModelTestPlaintextRequest {
  provider: string
  model_id: string
  api_key: string
  base_url?: string | null
  extra_config?: Record<string, unknown>
}

export interface TestConnectionResponse {
  ok: boolean
  latency_ms: number | null
  error: string | null
}

export interface AIModelUsageStage {
  stage: string
  label: string
}

export interface AIModelUsage {
  stages: readonly AIModelUsageStage[]
  /** Number of chat messages whose stage referenced this model. */
  chat_messages_count: number
  total_references: number
}

export interface AIModelDeleteConflict {
  /** Resources that reference this AI Model — admin must reassign first. */
  referenced_by: readonly {
    resource_type: string
    resource_id: string
    label: string
  }[]
}
