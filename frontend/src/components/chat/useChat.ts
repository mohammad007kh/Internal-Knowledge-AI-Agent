'use client'

import { useChatStream } from '@/hooks/use-chat-stream'
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

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
  send: (text: string) => void
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

  const [optimisticMessages, setOptimisticMessages] = useState<OptimisticMessage[]>([])
  const [clarification, setClarification] = useState<Clarification | null>(null)
  const [localGuardrail, setLocalGuardrail] = useState<string | null>(null)
  const [isPending, setIsPending] = useState(false)

  const pendingOptimisticIdRef = useRef<string | null>(null)
  const lastHandledMessageIdRef = useRef<string | null>(null)

  const clearOptimistic = useCallback(() => {
    const id = pendingOptimisticIdRef.current
    if (!id) return
    setOptimisticMessages((prev) => prev.filter((m) => m.id !== id))
    pendingOptimisticIdRef.current = null
  }, [])

  const send = useCallback(
    (text: string) => {
      if (!sessionId || !text.trim()) return

      const optimisticId = `optimistic-${Date.now()}`
      const optimisticMsg: OptimisticMessage = {
        id: optimisticId,
        role: 'user',
        content: text.trim(),
        created_at: new Date().toISOString(),
      }
      pendingOptimisticIdRef.current = optimisticId
      setOptimisticMessages((prev) => [...prev, optimisticMsg])
      setClarification(null)
      setLocalGuardrail(null)
      setIsPending(true)

      stream.sendMessage(sessionId, text.trim(), []).catch(() => {
        clearOptimistic()
        setIsPending(false)
        import('sonner')
          .then(({ toast }) => {
            toast.error('Failed to send message. Please try again.')
          })
          .catch(() => {})
      })
    },
    [sessionId, stream, clearOptimistic]
  )

  const abort = useCallback(() => {
    stream.abortStream()
    clearOptimistic()
    setIsPending(false)
  }, [stream, clearOptimistic])

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
        toast.error(msg)
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
