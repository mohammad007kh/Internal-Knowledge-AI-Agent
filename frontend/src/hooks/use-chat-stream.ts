'use client'

import { getToken } from '@/lib/token-store'
import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Citation shape from the backend SSE `citations` event.
 *
 * See T-007/T-008 for the streaming grammar. The backend emits
 *   event: citations
 *   data: { "citations": [{ "ref": 1, "source_name": "...", "excerpt": "...", "page": null }] }
 */
export interface StreamCitation {
  ref: number
  source_name: string
  excerpt: string
  page: number | null
}

/**
 * Discriminator describing the terminal state of the last (or current) stream.
 *
 * - `normal`           — regular assistant response, possibly with citations
 * - `clarification`    — agent asked a clarifying question (SSE `clarification_needed`)
 * - `guardrail_blocked`— request blocked by safety policy (SSE `guardrail_blocked`)
 * - `error`            — stream errored or fetch failed
 */
export type ChatStreamMessageType =
  | 'normal'
  | 'clarification'
  | 'guardrail_blocked'
  | 'error'

export interface UseChatStreamReturn {
  sendMessage: (sessionId: string, query: string, sourceIds?: string[]) => Promise<void>
  abortStream: () => void
  isStreaming: boolean
  currentResponse: string
  citations: StreamCitation[]
  messageType: ChatStreamMessageType
  clarificationQuestion: string | null
  guardrailMessage: string | null
  errorMessage: string | null
  lastMessageId: string | null
  /**
   * Clears local stream state — useful after the caller has persisted the
   * final assistant message into the query cache and wants a fresh buffer.
   */
  reset: () => void
}

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, '') ?? 'http://localhost:8000'

interface SseFrame {
  event: string
  data: string
}

/**
 * Parse a raw SSE frame (the text between two `\n\n` delimiters).
 * Returns `null` if the frame has no `data:` line.
 */
function parseSseFrame(raw: string): SseFrame | null {
  let event = 'message'
  const dataLines: string[] = []

  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice('data:'.length).trimStart())
    }
  }

  if (dataLines.length === 0) return null
  return { event, data: dataLines.join('\n') }
}

function safeJsonParse<T>(raw: string): T | null {
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

/**
 * Hook: manages a server-sent-events stream for chat message generation.
 *
 * Usage:
 *   const chat = useChatStream()
 *   await chat.sendMessage(sessionId, "Hello")
 *   // chat.currentResponse updates as tokens stream in
 *   // chat.citations populates on the `citations` event
 *   chat.abortStream() // cancel an in-flight stream
 *
 * Implementation notes:
 *  - Uses `fetch()` + `ReadableStream` (NOT `EventSource`) because
 *    the backend requires an `Authorization: Bearer` header and a POST body.
 *  - Manually attaches the Bearer token read from `@/lib/token-store`
 *    (the global axios interceptor does not apply to raw `fetch`).
 */
export function useChatStream(): UseChatStreamReturn {
  const [isStreaming, setIsStreaming] = useState(false)
  const [currentResponse, setCurrentResponse] = useState('')
  const [citations, setCitations] = useState<StreamCitation[]>([])
  const [messageType, setMessageType] = useState<ChatStreamMessageType>('normal')
  const [clarificationQuestion, setClarificationQuestion] = useState<string | null>(
    null
  )
  const [guardrailMessage, setGuardrailMessage] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [lastMessageId, setLastMessageId] = useState<string | null>(null)

  const controllerRef = useRef<AbortController | null>(null)

  // Abort any in-flight stream when the hook unmounts to prevent
  // setState-on-unmounted-component warnings and orphaned network requests.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
    }
  }, [])

  const abortStream = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
  }, [])

  const reset = useCallback(() => {
    setCurrentResponse('')
    setCitations([])
    setMessageType('normal')
    setClarificationQuestion(null)
    setGuardrailMessage(null)
    setErrorMessage(null)
    setLastMessageId(null)
  }, [])

  const sendMessage = useCallback(
    async (sessionId: string, query: string, sourceIds: string[] = []) => {
      if (!sessionId || !query.trim()) return

      // Abort any in-flight stream before starting a new one.
      controllerRef.current?.abort()
      const controller = new AbortController()
      controllerRef.current = controller

      setIsStreaming(true)
      setCurrentResponse('')
      setCitations([])
      setMessageType('normal')
      setClarificationQuestion(null)
      setGuardrailMessage(null)
      setErrorMessage(null)
      setLastMessageId(null)

      const token = getToken()
      const url = `${API_BASE}/api/v1/chat/sessions/${sessionId}/messages`

      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify({ query: query.trim(), source_ids: sourceIds }),
          credentials: 'include',
          signal: controller.signal,
        })

        if (!response.ok) {
          throw new Error(`Stream request failed with status ${response.status}`)
        }
        if (!response.body) {
          throw new Error('Stream response has no body')
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        // Drain the stream frame by frame. SSE frames are delimited by "\n\n".
        // Chunks arriving from the network may split mid-frame, so we buffer
        // until we have complete frames before parsing.
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const frames = buffer.split('\n\n')
          buffer = frames.pop() ?? ''

          for (const raw of frames) {
            if (!raw.trim()) continue
            const frame = parseSseFrame(raw)
            if (!frame) continue

            switch (frame.event) {
              case 'token': {
                const payload = safeJsonParse<{ delta?: string }>(frame.data)
                if (payload?.delta) {
                  setCurrentResponse((prev) => prev + payload.delta)
                }
                break
              }
              case 'citations': {
                const payload = safeJsonParse<{ citations?: StreamCitation[] }>(
                  frame.data
                )
                if (payload?.citations) {
                  setCitations(payload.citations)
                }
                break
              }
              case 'clarification_needed': {
                const payload = safeJsonParse<{ question?: string }>(frame.data)
                setMessageType('clarification')
                setClarificationQuestion(payload?.question ?? '')
                break
              }
              case 'guardrail_blocked': {
                const payload = safeJsonParse<{ message?: string }>(frame.data)
                setMessageType('guardrail_blocked')
                setGuardrailMessage(payload?.message ?? 'Request blocked by policy.')
                break
              }
              case 'done': {
                const payload = safeJsonParse<{ message_id?: string }>(frame.data)
                if (payload?.message_id) {
                  setLastMessageId(payload.message_id)
                }
                break
              }
              case 'error': {
                const payload = safeJsonParse<{ message?: string }>(frame.data)
                setMessageType('error')
                setErrorMessage(payload?.message ?? 'Stream error')
                break
              }
              default:
                // Unknown event types are ignored — forward compatibility.
                break
            }
          }
        }
      } catch (err) {
        // AbortError is the normal path for user-triggered cancellation.
        if (err instanceof DOMException && err.name === 'AbortError') {
          // Intentionally leave currentResponse populated so the caller can
          // decide whether to keep the partial message visible.
        } else {
          setMessageType('error')
          setErrorMessage(err instanceof Error ? err.message : 'Unknown error')
        }
      } finally {
        setIsStreaming(false)
        if (controllerRef.current === controller) {
          controllerRef.current = null
        }
      }
    },
    []
  )

  return {
    sendMessage,
    abortStream,
    isStreaming,
    currentResponse,
    citations,
    messageType,
    clarificationQuestion,
    guardrailMessage,
    errorMessage,
    lastMessageId,
    reset,
  }
}
