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
    // no `error`, no `clarification_needed`, no `guardrail_blocked`).
    // The reader closes cleanly — exactly the failure mode where the backend
    // bare-excepts a NotNullViolation mid-flight.
    const sseBody = 'event: token\ndata: {"delta":"partial"}\n\n'

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

    // Textarea must unlock — `isPending` controls the disabled state on the
    // ChatInputBar textarea via ChatLayout.
    await waitFor(() => {
      expect(result.current.isPending).toBe(false)
    })
    expect(result.current.isStreaming).toBe(false)
    // Optimistic user bubble must be cleared.
    expect(result.current.optimisticMessages).toEqual([])
    // An error toast must surface so the user knows something went wrong.
    expect(errorSpy).toHaveBeenCalled()
  })
})
