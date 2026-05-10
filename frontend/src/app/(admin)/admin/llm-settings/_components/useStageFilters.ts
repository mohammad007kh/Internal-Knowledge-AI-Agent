'use client'

import type { LlmStageConfig } from '@/lib/api/llm-settings'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

/**
 * Filter state for the LLM Settings page toolbar.
 *
 * Kept flat + serializable so it round-trips through URL params cleanly.
 * `providers` is order-insensitive but stored as a sorted list when written
 * to the URL to keep the param string stable across renders.
 */
export interface StageFilterState {
  /** Free-text search; tokenized on whitespace, ANDed across tokens. */
  search: string
  /** Selected providers (lowercased). Empty array = no filter. */
  providers: readonly string[]
  /** Status filter on `ai_model === null`. */
  status: 'all' | 'configured' | 'not_configured'
  /** Tri-state filter on non-empty `custom_prompt`. */
  customPrompt: 'any' | 'yes' | 'no'
}

/** Active filter chip for the chip strip below the toolbar. */
export interface ActiveChip {
  /** Stable id, unique within the active set. */
  id: string
  /** Short, human-readable label shown inside the chip. */
  label: string
  /** Removes just this chip's contribution from state. */
  remove: () => void
}

export interface UseStageFiltersResult {
  state: StageFilterState
  setState: (updater: (prev: StageFilterState) => StageFilterState) => void
  filteredStages: LlmStageConfig[]
  /** Distinct providers found in the input list (lowercased). */
  availableProviders: readonly string[]
  activeChips: readonly ActiveChip[]
  clearAll: () => void
  /** Convenience flag for callers that want to render an empty state. */
  hasActiveFilters: boolean
}

const DEFAULT_STATE: StageFilterState = {
  search: '',
  providers: [],
  status: 'all',
  customPrompt: 'any',
}

const SEARCH_DEBOUNCE_MS = 150

// ---- URL serialization ------------------------------------------------------

/** Read a {@link StageFilterState} from URL search params. */
export function parseStateFromParams(params: URLSearchParams): StageFilterState {
  const search = params.get('q')?.trim() ?? ''

  const providersRaw = params.get('provider')
  const providers = providersRaw
    ? providersRaw
        .split(',')
        .map((p) => p.trim().toLowerCase())
        .filter((p): p is string => p.length > 0)
    : []

  const statusRaw = params.get('status')
  const status: StageFilterState['status'] =
    statusRaw === 'configured' || statusRaw === 'not_configured' ? statusRaw : 'all'

  const cpRaw = params.get('custom_prompt')
  const customPrompt: StageFilterState['customPrompt'] =
    cpRaw === 'yes' || cpRaw === 'no' ? cpRaw : 'any'

  return { search, providers: dedupeSorted(providers), status, customPrompt }
}

/**
 * Serialize state to a URL query string fragment (no leading `?`).
 * Empty / default values are omitted so the URL stays clean.
 */
export function serializeStateToParams(state: StageFilterState): string {
  const params = new URLSearchParams()
  if (state.search.trim() !== '') params.set('q', state.search.trim())
  if (state.providers.length > 0) params.set('provider', dedupeSorted(state.providers).join(','))
  if (state.status !== 'all') params.set('status', state.status)
  if (state.customPrompt !== 'any') params.set('custom_prompt', state.customPrompt)
  return params.toString()
}

// ---- Filtering --------------------------------------------------------------

function tokenize(query: string): string[] {
  return query
    .toLowerCase()
    .split(/\s+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0)
}

function stageHaystack(stage: LlmStageConfig): string {
  const m = stage.ai_model
  return [
    stage.stage,
    stage.label,
    stage.description,
    m?.name ?? '',
    m?.model_id ?? '',
    m?.provider ?? '',
  ]
    .join(' ')
    .toLowerCase()
}

/** Pure filter function — exported for testing. */
export function applyStageFilters(
  stages: readonly LlmStageConfig[],
  state: StageFilterState
): LlmStageConfig[] {
  const tokens = tokenize(state.search)
  const providerSet = new Set(state.providers.map((p) => p.toLowerCase()))

  return stages.filter((stage) => {
    if (tokens.length > 0) {
      const haystack = stageHaystack(stage)
      const allMatch = tokens.every((t) => haystack.includes(t))
      if (!allMatch) return false
    }

    if (providerSet.size > 0) {
      const provider = stage.ai_model?.provider?.toLowerCase() ?? ''
      if (!provider || !providerSet.has(provider)) return false
    }

    if (state.status !== 'all') {
      const isConfigured = stage.ai_model !== null
      if (state.status === 'configured' && !isConfigured) return false
      if (state.status === 'not_configured' && isConfigured) return false
    }

    if (state.customPrompt !== 'any') {
      const hasPrompt = !!stage.custom_prompt && stage.custom_prompt.trim().length > 0
      if (state.customPrompt === 'yes' && !hasPrompt) return false
      if (state.customPrompt === 'no' && hasPrompt) return false
    }

    return true
  })
}

// ---- Helpers ----------------------------------------------------------------

function dedupeSorted(values: readonly string[]): string[] {
  return Array.from(new Set(values.map((v) => v.toLowerCase()))).sort((a, b) => a.localeCompare(b))
}

function statesEqual(a: StageFilterState, b: StageFilterState): boolean {
  if (a.search !== b.search) return false
  if (a.status !== b.status) return false
  if (a.customPrompt !== b.customPrompt) return false
  if (a.providers.length !== b.providers.length) return false
  const aSorted = dedupeSorted(a.providers)
  const bSorted = dedupeSorted(b.providers)
  for (let i = 0; i < aSorted.length; i++) {
    if (aSorted[i] !== bSorted[i]) return false
  }
  return true
}

function deriveAvailableProviders(stages: readonly LlmStageConfig[]): string[] {
  const set = new Set<string>()
  for (const s of stages) {
    const p = s.ai_model?.provider?.trim().toLowerCase()
    if (p) set.add(p)
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b))
}

// ---- Hook -------------------------------------------------------------------

/**
 * Owns search/filter state for the LLM Settings page, with URL sync.
 *
 * Behavior:
 *  - Reads URL params once on mount (initial state).
 *  - Writes URL via `router.replace` (no history spam) on subsequent changes.
 *  - Search input is debounced 150ms before being committed to URL/filter.
 *
 * Keeping the hook self-contained means the toolbar stays presentational.
 */
export function useStageFilters(stages: readonly LlmStageConfig[]): UseStageFiltersResult {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  // Read initial state from URL exactly once.
  const initialStateRef = useRef<StageFilterState | null>(null)
  if (initialStateRef.current === null) {
    initialStateRef.current = parseStateFromParams(
      searchParams ? new URLSearchParams(searchParams.toString()) : new URLSearchParams()
    )
  }

  const [state, setStateRaw] = useState<StageFilterState>(initialStateRef.current)

  const setState = useCallback(
    (updater: (prev: StageFilterState) => StageFilterState) => {
      setStateRaw((prev) => {
        const next = updater(prev)
        return statesEqual(prev, next) ? prev : next
      })
    },
    []
  )

  // Debounce search before committing to URL — but other filters apply
  // immediately, so we keep the full state for filtering and only debounce the
  // serialized URL write.
  const [debouncedSearch, setDebouncedSearch] = useState(state.search)
  useEffect(() => {
    if (debouncedSearch === state.search) return
    const handle = setTimeout(() => setDebouncedSearch(state.search), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(handle)
  }, [state.search, debouncedSearch])

  // Sync state -> URL. We only write when the *serialized* URL actually
  // changes — this means typing in the search box doesn't fire a write until
  // the debounce flushes (since `debouncedSearch` lags `state.search`).
  const isFirstUrlSync = useRef(true)
  const lastSerialized = useRef<string | null>(null)
  useEffect(() => {
    const stateForUrl: StageFilterState = { ...state, search: debouncedSearch }
    const qs = serializeStateToParams(stateForUrl)

    if (isFirstUrlSync.current) {
      // Skip the initial render so we don't replace the URL on mount.
      isFirstUrlSync.current = false
      lastSerialized.current = qs
      return
    }

    if (qs === lastSerialized.current) return
    lastSerialized.current = qs

    const target = qs ? `${pathname}?${qs}` : pathname
    router.replace(target, { scroll: false })
    // We deliberately exclude `router` and `pathname` from deps to avoid a
    // tight loop if the router identity changes; pathname is stable per page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state, debouncedSearch])

  const availableProviders = useMemo(() => deriveAvailableProviders(stages), [stages])

  const filteredStages = useMemo(() => applyStageFilters(stages, state), [stages, state])

  const clearAll = useCallback(() => {
    setStateRaw(DEFAULT_STATE)
  }, [])

  const activeChips = useMemo<ActiveChip[]>(() => {
    const chips: ActiveChip[] = []

    if (state.search.trim() !== '') {
      chips.push({
        id: 'search',
        label: `Search: "${state.search.trim()}"`,
        remove: () => setStateRaw((prev) => ({ ...prev, search: '' })),
      })
    }

    for (const provider of state.providers) {
      chips.push({
        id: `provider:${provider}`,
        label: `Provider: ${provider}`,
        remove: () =>
          setStateRaw((prev) => ({
            ...prev,
            providers: prev.providers.filter((p) => p !== provider),
          })),
      })
    }

    if (state.status !== 'all') {
      chips.push({
        id: 'status',
        label: `Status: ${state.status === 'configured' ? 'Configured' : 'Not configured'}`,
        remove: () => setStateRaw((prev) => ({ ...prev, status: 'all' })),
      })
    }

    if (state.customPrompt !== 'any') {
      chips.push({
        id: 'custom_prompt',
        label: `Custom prompt: ${state.customPrompt === 'yes' ? 'Yes' : 'No'}`,
        remove: () => setStateRaw((prev) => ({ ...prev, customPrompt: 'any' })),
      })
    }

    return chips
  }, [state])

  const hasActiveFilters =
    state.search.trim() !== '' ||
    state.providers.length > 0 ||
    state.status !== 'all' ||
    state.customPrompt !== 'any'

  return {
    state,
    setState,
    filteredStages,
    availableProviders,
    activeChips,
    clearAll,
    hasActiveFilters,
  }
}
