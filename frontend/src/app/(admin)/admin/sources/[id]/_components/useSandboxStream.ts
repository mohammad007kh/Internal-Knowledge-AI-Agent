'use client'

/**
 * Sandbox-mode chat streaming hook.
 *
 * The persistent chat (`useChatStream`) targets `POST /sessions/{id}/messages`
 * and depends on a server-side ChatSession that owns the message history.
 * The sandbox endpoint accepts the history inline on the request and never
 * persists. The wire grammar is intentionally byte-identical so we can
 * share the SSE-frame parser, but we don't share the hook itself — they
 * differ on URL, payload shape, and (most importantly) lifecycle: sandbox
 * state is purely browser-local and is wiped on tab close.
 *
 * State is `useState`-only by design — no React Query, no localStorage. A
 * hard refresh wipes everything. That property is part of the UX contract.
 */
import { openSandboxStream } from '@/lib/api/chat'
import {
  type ActivityState,
  activityLogReducer,
  emptyActivityState,
  parseAgentEvent,
} from '@/lib/sse/agent-events'
import { useCallback, useEffect, useRef, useState } from 'react'

export type SandboxMessageType = 'normal' | 'clarification' | 'guardrail_blocked' | 'error'

export interface SandboxStreamResult {
  /** True between `sendMessage()` and the terminal SSE frame (or abort). */
  isStreaming: boolean
  /** Tokens accumulated so far on the in-flight assistant turn. */
  currentResponse: string
  /** Type of the last terminal frame — drives banner / fallback rendering. */
  messageType: SandboxMessageType
  /** Populated when messageType==='clarification'. */
  clarificationQuestion: string | null
  /** Populated when messageType==='guardrail_blocked'. */
  guardrailMessage: string | null
  /** Populated when messageType==='error' (or fetch failed). */
  errorMessage: string | null
  /**
   * Per-turn agentic activity log folded from the INTERMEDIATE SSE events
   * (`plan`/`step`/`replan`/`budget`). Additive only — these events never end
   * the turn (no terminal flag, not in the `sawTerminal` set). Reset on every
   * `sendMessage()`. Consumed by the T-071+ thinking UI.
   */
  activityLog: ActivityState
  /** True for the brief gap between `sendMessage()` and the first event. */
  isPending: boolean
  /** Open the SSE stream, accumulate tokens. Returns once terminated. */
  sendMessage: (
    sourceId: string,
    query: string,
    history: ReadonlyArray<{ role: 'user' | 'assistant'; content: string }>
  ) => Promise<void>
  /** User-initiated cancellation. */
  abort: () => void
  /** Reset all stream state — call after persisting the final assistant turn. */
  reset: () => void
}

interface SseFrame {
  event: string
  data: string
}

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

export function useSandboxStream(): SandboxStreamResult {
  const [isStreaming, setIsStreaming] = useState(false)
  const [isPending, setIsPending] = useState(false)
  const [currentResponse, setCurrentResponse] = useState('')
  const [messageType, setMessageType] = useState<SandboxMessageType>('normal')
  const [clarificationQuestion, setClarificationQuestion] = useState<string | null>(null)
  const [guardrailMessage, setGuardrailMessage] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [activityLog, setActivityLog] = useState<ActivityState>(emptyActivityState)

  const controllerRef = useRef<AbortController | null>(null)

  // Cancel any in-flight stream when the consumer unmounts so we don't fire
  // setState on a torn-down tree.
  useEffect(() => {
    return () => {
      controllerRef.current?.abort()
    }
  }, [])

  const abort = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
    setIsPending(false)
  }, [])

  const reset = useCallback(() => {
    setCurrentResponse('')
    setMessageType('normal')
    setClarificationQuestion(null)
    setGuardrailMessage(null)
    setErrorMessage(null)
    setActivityLog(emptyActivityState)
  }, [])

  const sendMessage = useCallback(
    async (
      sourceId: string,
      query: string,
      history: ReadonlyArray<{ role: 'user' | 'assistant'; content: string }>
    ) => {
      if (!sourceId || !query.trim()) return

      controllerRef.current?.abort()
      const controller = new AbortController()
      controllerRef.current = controller

      setIsStreaming(true)
      setIsPending(true)
      setCurrentResponse('')
      setMessageType('normal')
      setClarificationQuestion(null)
      setGuardrailMessage(null)
      setErrorMessage(null)
      setActivityLog(emptyActivityState)

      try {
        const response = await openSandboxStream(
          { source_id: sourceId, query, history },
          controller.signal
        )

        // openSandboxStream guarantees a non-null body when it resolves
        // successfully. The `!` would still trip the strict-null guard
        // but the throw inside openSandboxStream covers the actual case.
        const body = response.body
        if (!body) {
          throw new Error('Sandbox stream response has no body')
        }
        const reader = body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let sawTerminal = false
        let firstEvent = true

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

            // First non-empty event clears the "thinking" pulse — once we
            // have ANY data on the wire (token, citations, terminal) the
            // user sees motion in the bubble, not pulsing dots.
            if (firstEvent) {
              firstEvent = false
              setIsPending(false)
            }

            switch (frame.event) {
              case 'delta': {
                const payload = safeJsonParse<{ token?: string }>(frame.data)
                if (payload?.token) {
                  setCurrentResponse((prev) => prev + payload.token)
                }
                break
              }
              case 'clarification': {
                const payload = safeJsonParse<{ question?: string }>(frame.data)
                setMessageType('clarification')
                setClarificationQuestion(payload?.question ?? '')
                sawTerminal = true
                break
              }
              case 'guardrail_blocked': {
                const payload = safeJsonParse<{ message?: string }>(frame.data)
                setMessageType('guardrail_blocked')
                setGuardrailMessage(payload?.message ?? 'Request blocked by policy.')
                sawTerminal = true
                break
              }
              case 'done': {
                sawTerminal = true
                break
              }
              case 'error': {
                const payload = safeJsonParse<{ message?: string }>(frame.data)
                setMessageType('error')
                setErrorMessage(payload?.message ?? 'Stream error')
                sawTerminal = true
                break
              }
              default: {
                // INTERMEDIATE agentic events (plan/step/replan/budget) are
                // additive to the activity log and NEVER terminal: they do NOT
                // set messageType, do NOT touch `sawTerminal`, and are folded
                // through the shared, immutable reducer. parseAgentEvent returns
                // null for any other (unknown / future) event → silent drop.
                const agentEvent = parseAgentEvent(frame.event, safeJsonParse(frame.data))
                if (agentEvent) {
                  setActivityLog((prev) => activityLogReducer(prev, agentEvent))
                }
                break
              }
            }
          }
        }

        if (!sawTerminal) {
          setMessageType('error')
          setErrorMessage('Stream closed unexpectedly')
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          // User cancelled — don't surface as an error.
        } else {
          setMessageType('error')
          setErrorMessage(err instanceof Error ? err.message : 'Unknown error')
        }
      } finally {
        setIsStreaming(false)
        setIsPending(false)
        if (controllerRef.current === controller) {
          controllerRef.current = null
        }
      }
    },
    []
  )

  return {
    isStreaming,
    isPending,
    currentResponse,
    messageType,
    clarificationQuestion,
    guardrailMessage,
    errorMessage,
    activityLog,
    sendMessage,
    abort,
    reset,
  }
}
