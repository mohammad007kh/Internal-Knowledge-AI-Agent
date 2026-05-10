import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  parseStateFromParams,
  serializeStateToParams,
  stateToApiParams,
  useAuditLogFilters,
} from '../useAuditLogFilters'

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
  usePathname: () => '/admin/audit-log',
  useSearchParams: () => currentSearchParams,
  useParams: () => ({}),
  redirect: vi.fn(),
}))

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
      action: '',
      resourceType: '',
      adminUserId: '',
      from: '',
      to: '',
      page: 1,
      pageSize: 50,
    })
  })

  it('parses every filter param', () => {
    const state = parseStateFromParams(
      new URLSearchParams(
        'q=acme&action=source.create&resource_type=source' +
          '&admin_user_id=11111111-2222-3333-4444-555555555555' +
          '&from=2026-01-01&to=2026-02-01&page=3&page_size=100'
      )
    )
    expect(state.search).toBe('acme')
    expect(state.action).toBe('source.create')
    expect(state.resourceType).toBe('source')
    expect(state.adminUserId).toBe('11111111-2222-3333-4444-555555555555')
    expect(state.from).toBe('2026-01-01')
    expect(state.to).toBe('2026-02-01')
    expect(state.page).toBe(3)
    expect(state.pageSize).toBe(100)
  })

  it('clamps invalid page / page_size to defaults', () => {
    const state = parseStateFromParams(
      new URLSearchParams('page=0&page_size=999')
    )
    expect(state.page).toBe(1)
    expect(state.pageSize).toBe(50)
  })

  it('treats the __all__ sentinel as "no filter" for action and resource_type', () => {
    // Defence in depth: the sentinel is only meant to live inside the Radix
    // Select component (Radix disallows '' as an item value). If it ever
    // leaks into the URL — e.g. a hand-edited link or a stale bookmark —
    // we must NOT round-trip it to the API.
    const state = parseStateFromParams(
      new URLSearchParams('action=__all__&resource_type=__all__')
    )
    expect(state.action).toBe('')
    expect(state.resourceType).toBe('')
  })
})

describe('serializeStateToParams', () => {
  it('omits default values from the URL', () => {
    expect(
      serializeStateToParams({
        search: '',
        action: '',
        resourceType: '',
        adminUserId: '',
        from: '',
        to: '',
        page: 1,
        pageSize: 50,
      })
    ).toBe('')
  })

  it('serialises a full state', () => {
    const qs = serializeStateToParams({
      search: 'acme',
      action: 'source.create',
      resourceType: 'source',
      adminUserId: '11111111-2222-3333-4444-555555555555',
      from: '2026-01-01',
      to: '2026-02-01',
      page: 3,
      pageSize: 100,
    })
    const params = new URLSearchParams(qs)
    expect(params.get('q')).toBe('acme')
    expect(params.get('action')).toBe('source.create')
    expect(params.get('resource_type')).toBe('source')
    expect(params.get('admin_user_id')).toBe(
      '11111111-2222-3333-4444-555555555555'
    )
    expect(params.get('from')).toBe('2026-01-01')
    expect(params.get('to')).toBe('2026-02-01')
    expect(params.get('page')).toBe('3')
    expect(params.get('page_size')).toBe('100')
  })
})

describe('stateToApiParams', () => {
  it('drops empty-string filter fields but preserves page / page_size', () => {
    const out = stateToApiParams({
      search: '',
      action: '',
      resourceType: '',
      adminUserId: '',
      from: '',
      to: '',
      page: 2,
      pageSize: 25,
    })
    expect(out).toEqual({ page: 2, page_size: 25 })
  })

  it('forwards every populated field', () => {
    const out = stateToApiParams({
      search: 'acme',
      action: 'source.create',
      resourceType: 'source',
      adminUserId: 'abc',
      from: '2026-01-01',
      to: '2026-02-01',
      page: 1,
      pageSize: 50,
    })
    expect(out).toEqual({
      page: 1,
      page_size: 50,
      search: 'acme',
      action: 'source.create',
      resource_type: 'source',
      admin_user_id: 'abc',
      from: '2026-01-01',
      to: '2026-02-01',
    })
  })

  it('trims whitespace from the search input', () => {
    const out = stateToApiParams({
      search: '   acme   ',
      action: '',
      resourceType: '',
      adminUserId: '',
      from: '',
      to: '',
      page: 1,
      pageSize: 50,
    })
    expect(out.search).toBe('acme')
  })
})

describe('useAuditLogFilters', () => {
  it('reads initial state from the URL on mount', () => {
    currentSearchParams = new URLSearchParams(
      'q=acme&action=source.update&page=2'
    )
    const { result } = renderHook(() => useAuditLogFilters())
    expect(result.current.state.search).toBe('acme')
    expect(result.current.state.action).toBe('source.update')
    expect(result.current.state.page).toBe(2)
    expect(result.current.hasActiveFilters).toBe(true)
  })

  it('produces active chips that can be removed individually', () => {
    currentSearchParams = new URLSearchParams(
      'q=acme&action=source.create&resource_type=source'
    )
    const { result } = renderHook(() => useAuditLogFilters())
    expect(result.current.activeChips.map((c) => c.id)).toEqual([
      'search',
      'action',
      'resource_type',
    ])

    act(() => {
      result.current.activeChips[1]?.remove()
    })
    expect(result.current.state.action).toBe('')
    expect(result.current.activeChips.map((c) => c.id)).toEqual([
      'search',
      'resource_type',
    ])
  })

  it('clearAll resets state to defaults', () => {
    currentSearchParams = new URLSearchParams(
      'q=acme&action=source.create&page=4'
    )
    const { result } = renderHook(() => useAuditLogFilters())
    expect(result.current.hasActiveFilters).toBe(true)

    act(() => {
      result.current.clearAll()
    })
    expect(result.current.state.search).toBe('')
    expect(result.current.state.action).toBe('')
    expect(result.current.state.page).toBe(1)
    expect(result.current.hasActiveFilters).toBe(false)
  })

  it('setPage changes only the page field', () => {
    const { result } = renderHook(() => useAuditLogFilters())
    act(() => {
      result.current.setPage(5)
    })
    expect(result.current.state.page).toBe(5)
  })

  it('setPageSize resets page to 1', () => {
    currentSearchParams = new URLSearchParams('page=4&page_size=25')
    const { result } = renderHook(() => useAuditLogFilters())
    expect(result.current.state.page).toBe(4)

    act(() => {
      result.current.setPageSize(100)
    })
    expect(result.current.state.pageSize).toBe(100)
    expect(result.current.state.page).toBe(1)
  })

  it('writes URL via router.replace when state changes (debounced search)', async () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useAuditLogFilters())

    // Status-style change writes URL without waiting on the search debounce.
    act(() => {
      result.current.setState((prev) => ({
        ...prev,
        action: 'source.create',
        page: 1,
      }))
    })
    await act(async () => {
      await vi.runAllTimersAsync()
    })
    expect(replaceMock).toHaveBeenCalled()
    expect(replaceMock.mock.calls.at(-1)?.[0]).toContain('action=source.create')

    // Search input only writes URL after the debounce flushes.
    replaceMock.mockClear()
    act(() => {
      result.current.setState((prev) => ({ ...prev, search: 'acme' }))
    })
    expect(replaceMock).not.toHaveBeenCalled()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300)
    })
    expect(replaceMock).toHaveBeenCalled()
    expect(replaceMock.mock.calls.at(-1)?.[0]).toContain('q=acme')
  })
})
