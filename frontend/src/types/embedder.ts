/**
 * Embedder resource types — mirrors `/api/v1/admin/embedders` shapes from
 * docs/ai-models-and-embedders-design.md §3 + §7.
 *
 * v1 invariants:
 *  - Exactly one embedder is active (partial unique index).
 *  - `dimensions` is read-only on PATCH.
 *  - Switching active embedder triggers a re-embed Celery job.
 */

import type { TestConnectionResponse, TestConnectionStatus } from '@/types/ai-model'

export type { TestConnectionResponse, TestConnectionStatus }

export interface EmbedderPublic {
  id: string
  name: string
  provider: string
  base_url: string | null
  model_id: string
  api_key_last4: string | null
  api_key_set: boolean
  extra_config: Record<string, unknown>
  dimensions: number
  max_input_tokens: number | null
  is_active: boolean
  last_test_at: string | null
  last_test_status: TestConnectionStatus
  last_test_error: string | null
  /** Number of sources currently referencing this embedder. */
  in_use_sources: number
  /** Number of chunks currently referencing this embedder. */
  in_use_chunks: number
  created_at: string
  updated_at: string
  created_by: string | null
}

export interface EmbedderListResponse {
  items: readonly EmbedderPublic[]
  total: number
  limit: number
  offset: number
}

export interface EmbedderCreateRequest {
  name: string
  provider: string
  model_id: string
  api_key: string
  dimensions: number
  base_url?: string | null
  extra_config?: Record<string, unknown>
  max_input_tokens?: number | null
}

export interface EmbedderUpdateRequest {
  name?: string
  provider?: string
  model_id?: string
  /** Omit/null to preserve existing key. */
  api_key?: string | null
  base_url?: string | null
  extra_config?: Record<string, unknown>
  max_input_tokens?: number | null
}

export interface EmbedderTestPlaintextRequest {
  provider: string
  model_id: string
  api_key: string
  dimensions: number
  base_url?: string | null
  extra_config?: Record<string, unknown>
}

/**
 * Dry-run preview returned by `GET /{id}/activate-preview`.
 *
 * No state change. Used to populate the activation confirmation dialog.
 */
export interface ActivateEmbedderPreview {
  chunks_to_reembed: number
  estimated_seconds: number
  estimated_api_cost_usd: number
  /** Provider family of the prospective embedder, e.g. ``"openai"``. */
  target_family: string
  /** Family/families of currently configured answer-generator LLMs. */
  active_llm_families: readonly string[]
  /** True when target embedder dimensions != 1536 (rejected in v1). */
  dimension_locked: boolean
  /** True when last_test_status is not ``ok`` within the last 24h. */
  untested: boolean
}

/**
 * Job kicked off by `POST /{id}/activate`. Frontend polls progress via the
 * job_id (status endpoint shape mirrors source-sync jobs).
 */
export interface ActivateEmbedderResponse {
  job_id: string
  status: 'queued' | 'validating' | 'reembedding' | 'completed' | 'failed'
  /** Human-readable progress message. */
  message: string | null
}
