'use client'

import { useChatStream } from '@/hooks/use-chat-stream'
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSelectedSession } from './SelectedSessionContext'

export interface OptimisticMessage {
  id: string
  role: 'user'
  content: string
  created_at: string
}

export interface Clarification {
  question: string
  messageId: string
}

export interface UseChatReturn {
  /**
   * Send a message into the active session.
   *
   * Accepts an optional `overrideSessionId` so callers that just created a
   * session (e.g. ChatLayout's "auto-create on send" path) can dispatch into
   * the new session in the same tick without waiting for the closed-over
   * `sessionId` prop to update on the next render.
   */
  send: (text: string, overrideSessionId?: string) => void
  abort: () => void
  isPending: boolean
  streamingToken: string
  isStreaming: boolean
  optimisticMessages: OptimisticMessage[]
  clarification: Clarification | null
  dismissClarification: () => void
  guardrailMessage: string | null
  dismissGuardrail: () => void
}

export function useChat({ sessionId }: { sessionId: string | null }): UseChatReturn {
  const queryClient = useQueryClient()
  const stream = useChatStream()
  const { registerAbortStream } = useSelectedSession()

  const [optimisticMessages, setOptimisticMessages] = useState<OptimisticMessage[]>([])
  const [clarification, setClarification] = useState<Clarification | null>(null)
  const [localGuardrail, setLocalGuardrail] = useState<string | null>(null)
  const [isPending, setIsPending] = useState(false)

  const pendingOptimisticIdRef = useRef<string | null>(null)
  const lastHandledMessageIdRef = useRef<string | null>(null)
  const lastQueryRef = useRef<string>('')
  const sendRef = useRef<(text: string, overrideSessionId?: string) => void>(() => {})

  const clearOptimistic = useCallback(() => {
    const id = pendingOptimisticIdRef.current
    if (!id) return
    setOptimisticMessages((prev) => prev.filter((m) => m.id !== id))
    pendingOptimisticIdRef.current = null
  }, [])

  const send = useCallback(
    (text: string, overrideSessionId?: string) => {
      // Prefer the explicit override so that callers which just created a
      // session can dispatch into it before React commits the state update
      // that propagates the new id through props.
      const targetSessionId = overrideSessionId ?? sessionId
      if (!targetSessionId || !text.trim()) return
      const trimmed = text.trim()
      lastQueryRef.current = trimmed

      // Clear any stale optimistic bubble from a previous in-flight send
      // so a rapid second send does not leave a ghost bubble behind.
      clearOptimistic()

      const optimisticId = `optimistic-${Date.now()}`
      const optimisticMsg: OptimisticMessage = {
        id: optimisticId,
        role: 'user',
        content: trimmed,
        created_at: new Date().toISOString(),
      }
      pendingOptimisticIdRef.current = optimisticId
      setOptimisticMessages((prev) => [...prev, optimisticMsg])
      setClarification(null)
      setLocalGuardrail(null)
      setIsPending(true)

      stream.sendMessage(targetSessionId, trimmed, []).catch(() => {
        clearOptimistic()
        setIsPending(false)
        import('sonner')
          .then(({ toast }) => {
            toast.error('Failed to send message. Please try again.', {
              action: {
                label: 'Retry',
                onClick: () => sendRef.current(lastQueryRef.current),
              },
            })
          })
          .catch(() => {})
      })
    },
    [sessionId, stream, clearOptimistic]
  )

  useEffect(() => {
    sendRef.current = send
  }, [send])

  const abort = useCallback(() => {
    stream.abortStream()
    clearOptimistic()
    setIsPending(false)
  }, [stream, clearOptimistic])

  // Abort any in-flight stream when the active session changes — switching
  // sessions (including deletion of the current one) must not leak a stream
  // that would then populate the wrong session's view on completion.
  // biome-ignore lint/correctness/useExhaustiveDependencies: only session switches should trigger this
  useEffect(() => {
    return () => {
      abort()
    }
  }, [sessionId])

  // Expose this instance's abort to the shared selection context so that
  // components outside the React tree that owns `useChat` (e.g. SessionList
  // when deleting the active session) can force-cancel an in-flight stream
  // before clearing the selection.
  useEffect(() => {
    return registerAbortStream(abort)
  }, [registerAbortStream, abort])

  const dismissClarification = useCallback(() => {
    setClarification(null)
  }, [])

  const dismissGuardrail = useCallback(() => {
    setLocalGuardrail(null)
  }, [])

  useEffect(() => {
    if (stream.messageType !== 'clarification') return
    if (!stream.clarificationQuestion) return
    setClarification({
      question: stream.clarificationQuestion,
      messageId: stream.lastMessageId ?? '',
    })
    clearOptimistic()
    setIsPending(false)
  }, [stream.messageType, stream.clarificationQuestion, stream.lastMessageId, clearOptimistic])

  useEffect(() => {
    if (stream.messageType !== 'guardrail_blocked') return
    if (!stream.guardrailMessage) return
    setLocalGuardrail(stream.guardrailMessage)
    clearOptimistic()
    setIsPending(false)
  }, [stream.messageType, stream.guardrailMessage, clearOptimistic])

  useEffect(() => {
    if (stream.messageType !== 'error') return
    clearOptimistic()
    setIsPending(false)
    const msg = stream.errorMessage ?? 'Stream error'
    import('sonner')
      .then(({ toast }) => {
        toast.error(msg, {
          action: {
            label: 'Retry',
            onClick: () => sendRef.current(lastQueryRef.current),
          },
        })
      })
      .catch(() => {})
  }, [stream.messageType, stream.errorMessage, clearOptimistic])

  useEffect(() => {
    const messageId = stream.lastMessageId
    if (!messageId) return
    if (lastHandledMessageIdRef.current === messageId) return
    lastHandledMessageIdRef.current = messageId

    clearOptimistic()
    setIsPending(false)

    if (sessionId) {
      queryClient.invalidateQueries({
        queryKey: ['chat-session-messages', sessionId],
      })
    }
    queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
  }, [stream.lastMessageId, sessionId, queryClient, clearOptimistic])

  return {
    send,
    abort,
    isPending,
    streamingToken: stream.currentResponse,
    isStreaming: stream.isStreaming,
    optimisticMessages,
    clarification,
    dismissClarification,
    guardrailMessage: localGuardrail,
    dismissGuardrail,
  }
}
