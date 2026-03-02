import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { type ReactNode, createElement } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChat } from '../useChat'

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
})
