/**
 * Provider catalog types — mirrors `GET /api/v1/admin/providers`.
 *
 * The catalog is static metadata about LLM and embedder providers, used to:
 *  - populate default base_url + suggested model IDs in forms
 *  - render provider Badges in pickers
 *  - drive cross-family pairing hints (cosmetic only)
 *
 * Family-tag semantics: see docs/ai-models-and-embedders-design.md §5.
 */

export type ProviderKind = 'llm' | 'embedder'

export interface ProviderModelSuggestion {
  /** Model identifier sent to the provider, e.g. "gpt-4o-mini". */
  model_id: string
  /** Display label, falls back to model_id when omitted. */
  label?: string
  /** Native dimensions for embedder suggestions. */
  dimensions?: number
}

export interface ProviderSpec {
  key: string
  display: string
  family_tag: string
  default_base_url: string | null
  /** ``true`` when ``base_url`` MUST be supplied by the admin (no provider default). */
  base_url_required: boolean
  /** Authentication scheme description — informational, not enforced client-side. */
  auth_scheme: string | null
  /** Provider-specific extra fields surfaced in the form. */
  extra_fields: readonly string[]
  /** Suggested LLM models for the provider. */
  llm_models: readonly ProviderModelSuggestion[]
  /** Suggested embedder models for the provider. */
  embedder_models: readonly ProviderModelSuggestion[]
  /** ``true`` when the provider has no native embedder offering (e.g. Anthropic). */
  embedder_unsupported: boolean
}

export interface ProviderCatalog {
  providers: readonly ProviderSpec[]
}
