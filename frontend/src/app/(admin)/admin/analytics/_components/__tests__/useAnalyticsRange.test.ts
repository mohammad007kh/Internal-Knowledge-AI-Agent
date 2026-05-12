import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  parseRangeFromParams,
  serializeRangeToParams,
  useAnalyticsRange,
} from '../useAnalyticsRange'

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
  usePathname: () => '/admin/analytics',
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

describe('parseRangeFromParams', () => {
  it('defaults to 7d when the param is missing', () => {
    expect(parseRangeFromParams(new URLSearchParams())).toBe('7d')
  })

  it('reads a valid range token', () => {
    expect(parseRangeFromParams(new URLSearchParams('range=30d'))).toBe('30d')
    expect(parseRangeFromParams(new URLSearchParams('range=24h'))).toBe('24h')
    expect(parseRangeFromParams(new URLSearchParams('range=90d'))).toBe('90d')
  })

  it('falls back to 7d for a junk token', () => {
    expect(parseRangeFromParams(new URLSearchParams('range=1y'))).toBe('7d')
    expect(parseRangeFromParams(new URLSearchParams('range='))).toBe('7d')
  })
})

describe('serializeRangeToParams', () => {
  it('omits the default (7d) from the URL', () => {
    expect(serializeRangeToParams('7d')).toBe('')
  })

  it('serialises a non-default range', () => {
    expect(serializeRangeToParams('30d')).toBe('range=30d')
    expect(serializeRangeToParams('24h')).toBe('range=24h')
  })
})

describe('useAnalyticsRange', () => {
  it('reads the initial range from the URL on mount', () => {
    currentSearchParams = new URLSearchParams('range=30d')
    const { result } = renderHook(() => useAnalyticsRange())
    expect(result.current.range).toBe('30d')
  })

  it('defaults to 7d with no param', () => {
    const { result } = renderHook(() => useAnalyticsRange())
    expect(result.current.range).toBe('7d')
  })

  it('does not write the URL on mount', () => {
    currentSearchParams = new URLSearchParams('range=90d')
    renderHook(() => useAnalyticsRange())
    expect(replaceMock).not.toHaveBeenCalled()
  })

  it('writes the URL via router.replace when the range changes', () => {
    const { result } = renderHook(() => useAnalyticsRange())
    act(() => {
      result.current.setRange('30d')
    })
    expect(replaceMock).toHaveBeenCalled()
    expect(replaceMock.mock.calls.at(-1)?.[0]).toContain('range=30d')
  })

  it('drops the param from the URL when switching back to 7d', () => {
    currentSearchParams = new URLSearchParams('range=30d')
    const { result } = renderHook(() => useAnalyticsRange())
    act(() => {
      result.current.setRange('7d')
    })
    expect(replaceMock).toHaveBeenCalled()
    expect(replaceMock.mock.calls.at(-1)?.[0]).toBe('/admin/analytics')
  })

  it('is a no-op when setting the same range', () => {
    const { result } = renderHook(() => useAnalyticsRange())
    act(() => {
      result.current.setRange('7d')
    })
    expect(replaceMock).not.toHaveBeenCalled()
  })
})
