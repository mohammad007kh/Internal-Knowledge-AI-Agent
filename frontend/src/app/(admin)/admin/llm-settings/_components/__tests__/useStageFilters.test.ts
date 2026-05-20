import type { LlmStageConfig } from '@/lib/api/llm-settings'
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  applyStageFilters,
  parseStateFromParams,
  serializeStateToParams,
  useStageFilters,
} from '../useStageFilters'

// Override the global mock to give us a programmable `useSearchParams` /
// `useRouter` per-test.
const replaceMock = vi.fn()
let currentSearchParams = new URLSearchParams()

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: replaceMock,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/admin/llm-settings',
  useSearchParams: () => currentSearchParams,
  useParams: () => ({}),
  redirect: vi.fn(),
}))

function makeStage(overrides: Partial<LlmStageConfig> & Pick<LlmStageConfig, 'stage'>): LlmStageConfig {
  return {
    stage: overrides.stage,
    label: overrides.label ?? 'Stage label',
    description: overrides.description ?? 'A pipeline stage',
    ai_model: overrides.ai_model ?? null,
    model: overrides.model ?? '',
    api_key_hint: overrides.api_key_hint ?? null,
    temperature: overrides.temperature ?? null,
    max_tokens: overrides.max_tokens ?? null,
    custom_prompt: overrides.custom_prompt ?? null,
  }
}

const SYNTHESIZER = makeStage({
  stage: 'synthesizer',
  label: 'Synthesizer',
  description: 'Generates the final answer',
  ai_model: {
    id: 'm1',
    name: 'GPT-4o',
    provider: 'openai',
    model_id: 'gpt-4o',
    capabilities: { tools: true, vision: false, structured_output: true } as never,
  },
  custom_prompt: 'You are a helpful assistant.',
})

const QUERY_ANALYZER = makeStage({
  stage: 'query_analyzer',
  label: 'Query analyzer',
  description: 'Decomposes the question',
  ai_model: {
    id: 'm2',
    name: 'Claude Sonnet',
    provider: 'anthropic',
    model_id: 'claude-3-5-sonnet',
    capabilities: { tools: true, vision: false, structured_output: true } as never,
  },
  custom_prompt: null,
})

const REFLECTOR = makeStage({
  stage: 'reflector',
  label: 'Reflector',
  description: 'Reviews the draft answer',
  ai_model: null,
  custom_prompt: '   ',
})

const STAGES: LlmStageConfig[] = [SYNTHESIZER, QUERY_ANALYZER, REFLECTOR]

beforeEach(() => {
  replaceMock.mockReset()
  currentSearchParams = new URLSearchParams()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('parseStateFromParams', () => {
  it('returns defaults for empty params', () => {
    const state = parseStateFromParams(new URLSearchParams())
    expect(state).toEqual({
      search: '',
      providers: [],
      status: 'all',
      customPrompt: 'any',
    })
  })

  it('parses URL params on mount', () => {
    const state = parseStateFromParams(
      new URLSearchParams('q=gpt&provider=openai,anthropic&status=configured&custom_prompt=yes')
    )
    expect(state.search).toBe('gpt')
    expect(state.providers).toEqual(['anthropic', 'openai'])
    expect(state.status).toBe('configured')
    expect(state.customPrompt).toBe('yes')
  })

  it('ignores invalid status / custom_prompt values', () => {
    const state = parseStateFromParams(
      new URLSearchParams('status=bogus&custom_prompt=maybe')
    )
    expect(state.status).toBe('all')
    expect(state.customPrompt).toBe('any')
  })
})

describe('serializeStateToParams', () => {
  it('omits default values', () => {
    expect(
      serializeStateToParams({
        search: '',
        providers: [],
        status: 'all',
        customPrompt: 'any',
      })
    ).toBe('')
  })

  it('serializes a full state with sorted providers', () => {
    const qs = serializeStateToParams({
      search: 'gpt synth',
      providers: ['openai', 'anthropic'],
      status: 'not_configured',
      customPrompt: 'no',
    })
    const params = new URLSearchParams(qs)
    expect(params.get('q')).toBe('gpt synth')
    expect(params.get('provider')).toBe('anthropic,openai')
    expect(params.get('status')).toBe('not_configured')
    expect(params.get('custom_prompt')).toBe('no')
  })
})

describe('applyStageFilters', () => {
  it('returns input unchanged when state is empty (default)', () => {
    expect(
      applyStageFilters(STAGES, {
        search: '',
        providers: [],
        status: 'all',
        customPrompt: 'any',
      })
    ).toEqual(STAGES)
  })

  it('tokenizes search and ANDs across tokens', () => {
    const result = applyStageFilters(STAGES, {
      search: 'gpt synth',
      providers: [],
      status: 'all',
      customPrompt: 'any',
    })
    expect(result).toHaveLength(1)
    expect(result[0]?.stage).toBe('synthesizer')
  })

  it('matches against label, description, model fields, and provider', () => {
    const byProvider = applyStageFilters(STAGES, {
      search: 'anthropic',
      providers: [],
      status: 'all',
      customPrompt: 'any',
    })
    expect(byProvider.map((s) => s.stage)).toEqual(['query_analyzer'])

    const byDescription = applyStageFilters(STAGES, {
      search: 'reviews',
      providers: [],
      status: 'all',
      customPrompt: 'any',
    })
    expect(byDescription.map((s) => s.stage)).toEqual(['reflector'])
  })

  it('applies multi-select provider filter', () => {
    const result = applyStageFilters(STAGES, {
      search: '',
      providers: ['openai', 'anthropic'],
      status: 'all',
      customPrompt: 'any',
    })
    expect(result.map((s) => s.stage).sort()).toEqual(['query_analyzer', 'synthesizer'])
  })

  it('applies status=configured', () => {
    const result = applyStageFilters(STAGES, {
      search: '',
      providers: [],
      status: 'configured',
      customPrompt: 'any',
    })
    expect(result.map((s) => s.stage).sort()).toEqual(['query_analyzer', 'synthesizer'])
  })

  it('applies status=not_configured', () => {
    const result = applyStageFilters(STAGES, {
      search: '',
      providers: [],
      status: 'not_configured',
      customPrompt: 'any',
    })
    expect(result.map((s) => s.stage)).toEqual(['reflector'])
  })

  it('applies custom_prompt=yes (treats whitespace-only as empty)', () => {
    const result = applyStageFilters(STAGES, {
      search: '',
      providers: [],
      status: 'all',
      customPrompt: 'yes',
    })
    expect(result.map((s) => s.stage)).toEqual(['synthesizer'])
  })

  it('applies custom_prompt=no', () => {
    const result = applyStageFilters(STAGES, {
      search: '',
      providers: [],
      status: 'all',
      customPrompt: 'no',
    })
    // QUERY_ANALYZER (null) and REFLECTOR (whitespace-only) both count as "no".
    expect(result.map((s) => s.stage).sort()).toEqual(['query_analyzer', 'reflector'])
  })
})

describe('useStageFilters', () => {
  it('reads initial state from URL on mount', () => {
    currentSearchParams = new URLSearchParams(
      'q=claude&provider=anthropic&status=configured&custom_prompt=no'
    )
    const { result } = renderHook(() => useStageFilters(STAGES))
    expect(result.current.state.search).toBe('claude')
    expect(result.current.state.providers).toEqual(['anthropic'])
    expect(result.current.state.status).toBe('configured')
    expect(result.current.state.customPrompt).toBe('no')
    expect(result.current.filteredStages.map((s) => s.stage)).toEqual(['query_analyzer'])
  })

  it('exposes derived available providers (deduped, sorted)', () => {
    const { result } = renderHook(() => useStageFilters(STAGES))
    expect(result.current.availableProviders).toEqual(['anthropic', 'openai'])
  })

  it('produces active chips that can each be removed individually', () => {
    currentSearchParams = new URLSearchParams('q=gpt&provider=openai&status=configured')
    const { result } = renderHook(() => useStageFilters(STAGES))
    expect(result.current.activeChips.map((c) => c.id)).toEqual([
      'search',
      'provider:openai',
      'status',
    ])

    act(() => {
      result.current.activeChips[1]?.remove()
    })
    expect(result.current.state.providers).toEqual([])
    expect(result.current.activeChips.map((c) => c.id)).toEqual(['search', 'status'])
  })

  it('clearAll resets state to defaults', () => {
    currentSearchParams = new URLSearchParams('q=gpt&provider=openai&status=configured')
    const { result } = renderHook(() => useStageFilters(STAGES))
    expect(result.current.hasActiveFilters).toBe(true)

    act(() => {
      result.current.clearAll()
    })

    expect(result.current.state).toEqual({
      search: '',
      providers: [],
      status: 'all',
      customPrompt: 'any',
    })
    expect(result.current.hasActiveFilters).toBe(false)
  })

  it('writes URL via router.replace when state changes (debounced search)', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useStageFilters(STAGES))

    act(() => {
      result.current.setState((prev) => ({ ...prev, status: 'configured' }))
    })
    // Status change writes URL immediately (still passes through the search-
    // debounce effect, but search hasn't changed so the debounced value is
    // already in sync).
    await act(async () => {
      await vi.runAllTimersAsync()
    })

    expect(replaceMock).toHaveBeenCalled()
    const lastCall = replaceMock.mock.calls.at(-1)?.[0]
    expect(typeof lastCall).toBe('string')
    expect(lastCall).toContain('status=configured')

    // Typing in search shouldn't write the URL until the debounce flushes.
    replaceMock.mockClear()
    act(() => {
      result.current.setState((prev) => ({ ...prev, search: 'gpt' }))
    })
    expect(replaceMock).not.toHaveBeenCalled()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(160)
    })
    expect(replaceMock).toHaveBeenCalled()
    const afterDebounce = replaceMock.mock.calls.at(-1)?.[0]
    expect(afterDebounce).toContain('q=gpt')
  })
})
