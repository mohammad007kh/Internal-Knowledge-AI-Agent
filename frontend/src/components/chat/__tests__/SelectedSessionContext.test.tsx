import { act, renderHook } from '@testing-library/react'
import * as nextNavigation from 'next/navigation'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SelectedSessionProvider, useSelectedSession } from '../SelectedSessionContext'

// We assert that `setSessionId(...)` translates to `router.push('/chat/<id>')`
// (or `router.replace(...)` when the `replace` option is set), and that the
// `sessionId` returned by the context mirrors the URL's `[sessionId]` param.

const pushMock = vi.fn()
const replaceMock = vi.fn()

beforeEach(() => {
  pushMock.mockReset()
  replaceMock.mockReset()
  vi.spyOn(nextNavigation, 'useRouter').mockReturnValue({
    push: pushMock,
    replace: replaceMock,
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
    // biome-ignore lint/suspicious/noExplicitAny: AppRouterInstance has more fields than the unit-test surface needs
  } as any)
})

afterEach(() => {
  vi.restoreAllMocks()
})

function wrapper({ children }: { children: ReactNode }) {
  return <SelectedSessionProvider>{children}</SelectedSessionProvider>
}

describe('SelectedSessionContext', () => {
  it('reads sessionId from useParams', () => {
    vi.spyOn(nextNavigation, 'useParams').mockReturnValue({ sessionId: 'abc-123' })
    const { result } = renderHook(() => useSelectedSession(), { wrapper })
    expect(result.current.sessionId).toBe('abc-123')
  })

  it('returns null sessionId when route has no [sessionId] segment', () => {
    vi.spyOn(nextNavigation, 'useParams').mockReturnValue({})
    const { result } = renderHook(() => useSelectedSession(), { wrapper })
    expect(result.current.sessionId).toBeNull()
  })

  it('setSessionId(id) navigates via router.push', () => {
    vi.spyOn(nextNavigation, 'useParams').mockReturnValue({})
    const { result } = renderHook(() => useSelectedSession(), { wrapper })
    act(() => result.current.setSessionId('xyz-789'))
    expect(pushMock).toHaveBeenCalledWith('/chat/xyz-789')
    expect(replaceMock).not.toHaveBeenCalled()
  })

  it('setSessionId(id, { replace: true }) navigates via router.replace', () => {
    vi.spyOn(nextNavigation, 'useParams').mockReturnValue({})
    const { result } = renderHook(() => useSelectedSession(), { wrapper })
    act(() => result.current.setSessionId('xyz-789', { replace: true }))
    expect(replaceMock).toHaveBeenCalledWith('/chat/xyz-789')
    expect(pushMock).not.toHaveBeenCalled()
  })

  it('setSessionId(null) navigates back to /chat (empty hero)', () => {
    vi.spyOn(nextNavigation, 'useParams').mockReturnValue({ sessionId: 'abc' })
    const { result } = renderHook(() => useSelectedSession(), { wrapper })
    act(() => result.current.setSessionId(null))
    expect(pushMock).toHaveBeenCalledWith('/chat')
  })

  it('preserves registerAbortStream / abortStream wiring', () => {
    vi.spyOn(nextNavigation, 'useParams').mockReturnValue({})
    const { result } = renderHook(() => useSelectedSession(), { wrapper })
    const handler = vi.fn()
    let unregister: (() => void) | null = null
    act(() => {
      unregister = result.current.registerAbortStream(handler)
    })
    act(() => result.current.abortStream())
    expect(handler).toHaveBeenCalledTimes(1)
    act(() => unregister?.())
    act(() => result.current.abortStream())
    // Handler is unregistered, so no further calls.
    expect(handler).toHaveBeenCalledTimes(1)
  })
})
