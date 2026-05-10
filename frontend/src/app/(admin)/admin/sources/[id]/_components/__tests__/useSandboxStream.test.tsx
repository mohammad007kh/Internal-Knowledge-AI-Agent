/**
 * useSandboxStream — SSE consumer for the admin sandbox tab.
 *
 * Locks the contract that previously broke "I sent a message and got
 * nothing back": the hook MUST accumulate the assistant turn into
 * ``currentResponse`` from the wire stream so the consuming component
 * (TestTab) can fold the completed turn into its messages array.
 *
 * If the backend ever stops emitting ``delta`` frames for the answer
 * text, this test should fail loudly — it pinned down the regression
 * after the synthetic-delta fix on the backend stream service.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the token store before importing anything that touches it.
vi.mock('@/lib/token-store', () => ({
  getToken: () => 'test-token',
  setToken: vi.fn(),
}))

import { useSandboxStream } from '../useSandboxStream'

// ---------------------------------------------------------------------------
// Helpers — build a realistic SSE Response from a list of frames.
// ---------------------------------------------------------------------------

function sseFrame(event: string, data: Record<string, unknown>): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

function makeStreamResponse(frames: string[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder()
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame))
      }
      controller.close()
    },
  })
  return new Response(body, {
    status,
    headers: { 'content-type': 'text/event-stream' },
  })
}

function makeJsonErrorResponse(status: number, body: object): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// Tests — happy paths
// ---------------------------------------------------------------------------

describe('useSandboxStream — currentResponse accumulation (regression)', () => {
  it('accumulates a single delta + done into currentResponse', async () => {
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame('delta', { token: 'Hello world' }),
        sseFrame('done', {
          session_id: '__sandbox__',
          message_id: '',
          trace_id: 't-1',
          sources: [],
        }),
      ])
    )

    const { result } = renderHook(() => useSandboxStream())

    await act(async () => {
      await result.current.sendMessage('src-1', 'hi', [])
    })

    // The bug: previously currentResponse stayed empty because the
    // backend never emitted a delta frame, only `done`. The test asserts
    // that a delta frame populates currentResponse.
    expect(result.current.currentResponse).toBe('Hello world')
    expect(result.current.messageType).toBe('normal')
    expect(result.current.errorMessage).toBeNull()
    expect(result.current.isStreaming).toBe(false)
  })

  it('concatenates multiple delta frames in arrival order', async () => {
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame('delta', { token: 'Hello' }),
        sseFrame('delta', { token: ' ' }),
        sseFrame('delta', { token: 'world' }),
        sseFrame('done', { session_id: '__sandbox__', message_id: '', sources: [] }),
      ])
    )

    const { result } = renderHook(() => useSandboxStream())

    await act(async () => {
      await result.current.sendMessage('src-1', 'hi', [])
    })

    expect(result.current.currentResponse).toBe('Hello world')
  })

  it('surfaces stream-closed-without-terminal as an error', async () => {
    // No `done` / `error` / `clarification` / `guardrail_blocked` ever
    // arrives — the stream just ends after a partial delta. This used
    // to be the silent-failure mode of the bug.
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([sseFrame('delta', { token: 'partial' })])
    )

    const { result } = renderHook(() => useSandboxStream())

    await act(async () => {
      await result.current.sendMessage('src-1', 'hi', [])
    })

    expect(result.current.messageType).toBe('error')
    expect(result.current.errorMessage).toMatch(/closed unexpectedly/i)
  })

  it('captures the URL and bearer token on the outgoing request', async () => {
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame('delta', { token: 'ok' }),
        sseFrame('done', { session_id: '__sandbox__', message_id: '', sources: [] }),
      ])
    )

    const { result } = renderHook(() => useSandboxStream())

    await act(async () => {
      await result.current.sendMessage('src-42', 'q?', [])
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(String(url)).toMatch(/\/api\/v1\/chat\/sandbox\/stream$/)
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe('Bearer test-token')
    expect(init.headers.Accept).toBe('text/event-stream')

    const body = JSON.parse(init.body as string)
    expect(body.source_id).toBe('src-42')
    expect(body.query).toBe('q?')
  })
})

// ---------------------------------------------------------------------------
// Tests — alternate terminal events
// ---------------------------------------------------------------------------

describe('useSandboxStream — terminal frames', () => {
  it('captures a clarification ask', async () => {
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame('clarification', { question: 'Which source?' }),
      ])
    )

    const { result } = renderHook(() => useSandboxStream())

    await act(async () => {
      await result.current.sendMessage('src-1', 'hi', [])
    })

    expect(result.current.messageType).toBe('clarification')
    expect(result.current.clarificationQuestion).toBe('Which source?')
  })

  it('captures a guardrail block', async () => {
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame('guardrail_blocked', { message: 'Policy violation' }),
      ])
    )

    const { result } = renderHook(() => useSandboxStream())

    await act(async () => {
      await result.current.sendMessage('src-1', 'hi', [])
    })

    expect(result.current.messageType).toBe('guardrail_blocked')
    expect(result.current.guardrailMessage).toBe('Policy violation')
  })

  it('captures an error frame', async () => {
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame('error', { message: 'Pipeline blew up', code: 'pipeline_error' }),
      ])
    )

    const { result } = renderHook(() => useSandboxStream())

    await act(async () => {
      await result.current.sendMessage('src-1', 'hi', [])
    })

    expect(result.current.messageType).toBe('error')
    expect(result.current.errorMessage).toBe('Pipeline blew up')
  })
})

// ---------------------------------------------------------------------------
// Tests — non-2xx responses
// ---------------------------------------------------------------------------

describe('useSandboxStream — HTTP errors', () => {
  it('surfaces a 403 detail string as the error message', async () => {
    fetchMock.mockResolvedValueOnce(
      makeJsonErrorResponse(403, { detail: 'Requires role: admin' })
    )

    const { result } = renderHook(() => useSandboxStream())

    await act(async () => {
      await result.current.sendMessage('src-1', 'hi', [])
    })

    expect(result.current.messageType).toBe('error')
    expect(result.current.errorMessage).toBe('Requires role: admin')
  })

  it('surfaces a 404 problem-details title', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ title: 'Source not found' }), {
        status: 404,
        headers: { 'content-type': 'application/problem+json' },
      })
    )

    const { result } = renderHook(() => useSandboxStream())

    await act(async () => {
      await result.current.sendMessage('src-1', 'hi', [])
    })

    expect(result.current.messageType).toBe('error')
    expect(result.current.errorMessage).toBe('Source not found')
  })
})

// ---------------------------------------------------------------------------
// Tests — guard rails
// ---------------------------------------------------------------------------

describe('useSandboxStream — guard rails', () => {
  it('no-ops on empty source id', async () => {
    const { result } = renderHook(() => useSandboxStream())
    await act(async () => {
      await result.current.sendMessage('', 'hi', [])
    })
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.isStreaming).toBe(false)
  })

  it('no-ops on whitespace-only query', async () => {
    const { result } = renderHook(() => useSandboxStream())
    await act(async () => {
      await result.current.sendMessage('src-1', '   ', [])
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('reset() clears all stream state', async () => {
    fetchMock.mockResolvedValueOnce(
      makeStreamResponse([
        sseFrame('delta', { token: 'something' }),
        sseFrame('done', { session_id: '__sandbox__', message_id: '', sources: [] }),
      ])
    )
    const { result } = renderHook(() => useSandboxStream())
    await act(async () => {
      await result.current.sendMessage('src-1', 'hi', [])
    })
    expect(result.current.currentResponse).toBe('something')
    await waitFor(() => expect(result.current.isStreaming).toBe(false))

    act(() => {
      result.current.reset()
    })
    expect(result.current.currentResponse).toBe('')
    expect(result.current.messageType).toBe('normal')
  })
})
