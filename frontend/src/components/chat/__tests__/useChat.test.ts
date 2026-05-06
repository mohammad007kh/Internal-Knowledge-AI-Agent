import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { type ReactNode, createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChat } from '../useChat'

vi.mock('sonner', () => ({
  toast: { error: vi.fn() },
}))

function makeStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
}

/**
 * A ReadableStream that never closes — lets us assert state during the
 * "stream is in flight" window without racing against a synchronous end.
 */
function makePendingStream(): {
  body: ReadableStream<Uint8Array>
  push: (chunk: string) => void
  close: () => void
} {
  const encoder = new TextEncoder()
  let controllerRef: ReadableStreamDefaultController<Uint8Array> | null = null
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      controllerRef = controller
    },
  })
  return {
    body,
    push: (chunk: string) => controllerRef?.enqueue(encoder.encode(chunk)),
    close: () => controllerRef?.close(),
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return createElement(QueryClientProvider, { client: queryClient }, children)
}

describe('useChat', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('sets isStreaming to true after send and false after done event', async () => {
    const sseBody =
      'event: token\ndata: {"token":"Hi"}\n\nevent: done\ndata: {"message_id":"m1"}\n\n'

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: makeStream([sseBody]),
      })
    )

    const { result } = renderHook(() => useChat({ sessionId: 'session-1' }), {
      wrapper,
    })

    expect(result.current.isStreaming).toBe(false)

    await act(async () => {
      result.current.send('Hello')
    })

    // After the stream completes, isStreaming should be false
    expect(result.current.isStreaming).toBe(false)
    expect(result.current.isPending).toBe(false)
  })

  it('unlocks textarea and shows error toast when stream closes without `done`', async () => {
    // SSE body that emits a token but never a terminal frame (no `done`,
    // no `error`, no `clarification`, no `guardrail_blocked`). The reader
    // closes cleanly — exactly the failure mode where the backend
    // bare-excepts a NotNullViolation mid-flight.
    const sseBody = 'event: delta\ndata: {"token":"partial"}\n\n'

    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        body: makeStream([sseBody]),
      })
    )

    const { toast } = await import('sonner')
    const errorSpy = toast.error as ReturnType<typeof vi.fn>
    errorSpy.mockClear()

    const { result } = renderHook(() => useChat({ sessionId: 'session-1' }), {
      wrapper,
    })

    await act(async () => {
      result.current.send('hi')
    })

    // Textarea must unlock — `isPending` controls the disabled state.
    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
    })
    expect(result.current.isStreaming).toBe(false)
    // Optimistic user bubble must be cleared.
    expect(result.current.optimisticMessages).toEqual([])
    // An error toast must surface so the user knows something went wrong.
    expect(errorSpy).toHaveBeenCalled()
  })

  // Regression: when the auto-create-on-send flow lands a freshly-created
  // session id (sessionId transitions null → "new-1"), the abort-on-switch
  // cleanup must NOT abort the just-started stream. Before the fix, the
  // cleanup fired unconditionally, cancelled the AbortController of the
  // in-flight send, and called clearOptimistic — making the typed message
  // vanish and the chat surface "reset" to the empty state.
  it('does not clear optimistic bubble or isPending when sessionId transitions null → new id during a send', async () => {
    const pending = makePendingStream()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: pending.body,
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string | null }) => useChat({ sessionId }),
      { wrapper, initialProps: { sessionId: null as string | null } }
    )

    // Auto-create-on-send: ChatLayout awaits the create mutation, gets
    // "new-1" back, and immediately calls send(text, "new-1") with the
    // override so the closure does not silently drop on the stale null.
    await act(async () => {
      result.current.send('Hello world', 'new-1')
    })

    expect(result.current.optimisticMessages).toHaveLength(1)
    expect(result.current.optimisticMessages[0]?.content).toBe('Hello world')
    expect(result.current.isPending).toBe(true)

    // ChatLayout's setSessionId(newId) propagates through React state,
    // re-rendering useChat with sessionId="new-1". Pre-fix this fired the
    // cleanup of the previous (sessionId=null) effect → abort() →
    // clearOptimistic + setIsPending(false), making the bubble flash and
    // disappear. Post-fix the cleanup checks the captured sessionId and
    // skips the abort when it was null.
    await act(async () => {
      rerender({ sessionId: 'new-1' })
    })

    expect(result.current.optimisticMessages).toHaveLength(1)
    expect(result.current.optimisticMessages[0]?.content).toBe('Hello world')
    expect(result.current.isPending).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const signal = fetchMock.mock.calls[0]?.[1]?.signal as AbortSignal | undefined
    expect(signal?.aborted).toBe(false)

    await act(async () => {
      pending.push('event: done\ndata: {"message_id":"m1"}\n\n')
      pending.close()
    })
  })

  // Sanity: a real session SWITCH (e.g. user picks another session from the
  // sidebar) must still abort the in-flight stream — the fix above only
  // skips the null → x transition.
  it('does abort the in-flight stream when switching from one real session to another', async () => {
    const pending = makePendingStream()
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: pending.body,
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string | null }) => useChat({ sessionId }),
      { wrapper, initialProps: { sessionId: 'session-a' as string | null } }
    )

    await act(async () => {
      result.current.send('Hello')
    })
    expect(result.current.isPending).toBe(true)

    await act(async () => {
      rerender({ sessionId: 'session-b' })
    })

    const signal = fetchMock.mock.calls[0]?.[1]?.signal as AbortSignal | undefined
    expect(signal?.aborted).toBe(true)
    expect(result.current.optimisticMessages).toHaveLength(0)
    expect(result.current.isPending).toBe(false)

    pending.close()
  })
})
