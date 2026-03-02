'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useRef, useState } from 'react'

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
  isPending: boolean
  streamingToken: string
  isStreaming: boolean
  optimisticMessages: OptimisticMessage[]
  clarification: Clarification | null
  dismissClarification: () => void
}

export function useChat({ sessionId }: { sessionId: string | null }): UseChatReturn {
  const queryClient = useQueryClient()
  const [isPending, setIsPending] = useState(false)
  const [streamingToken, setStreamingToken] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [optimisticMessages, setOptimisticMessages] = useState<OptimisticMessage[]>([])
  const [clarification, setClarification] = useState<Clarification | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const dismissClarification = useCallback(() => {
    setClarification(null)
  }, [])

  const send = useCallback(
    (text: string) => {
      if (!sessionId || !text.trim()) return

      // Abort any in-flight request
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller

      // Add optimistic message
      const optimisticId = `optimistic-${Date.now()}`
      const optimisticMsg: OptimisticMessage = {
        id: optimisticId,
        role: 'user',
        content: text.trim(),
        created_at: new Date().toISOString(),
      }
      setOptimisticMessages((prev) => [...prev, optimisticMsg])
      setIsPending(true)
      setIsStreaming(false)
      setStreamingToken('')

      const apiBase =
        process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000/api/v1'
      const url = `${apiBase}/chat/sessions/${sessionId}/stream`

      fetch(url, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text.trim() }),
        signal: controller.signal,
      })
        .then(async (response) => {
          if (!response.ok) {
            throw new Error(`HTTP ${response.status}`)
          }
          if (!response.body) {
            throw new Error('No response body')
          }

          setIsStreaming(true)

          const reader = response.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''

          while (true) {
            const { done, value } = await reader.read()
            if (done) break

            buffer += decoder.decode(value, { stream: true })

            // Process complete SSE frames (delimited by \n\n)
            const frames = buffer.split('\n\n')
            buffer = frames.pop() ?? ''

            for (const frame of frames) {
              if (!frame.trim()) continue

              let eventType = 'message'
              let dataStr = ''

              for (const line of frame.split('\n')) {
                if (line.startsWith('event:')) {
                  eventType = line.slice('event:'.length).trim()
                } else if (line.startsWith('data:')) {
                  dataStr = line.slice('data:'.length).trim()
                }
              }

              if (!dataStr) continue

              let payload: Record<string, string>
              try {
                payload = JSON.parse(dataStr)
              } catch {
                continue
              }

              if (eventType === 'token') {
                setStreamingToken((prev) => prev + (payload.token ?? ''))
              } else if (eventType === 'done') {
                // Clear optimistic message and streaming state, then invalidate queries
                setOptimisticMessages((prev) =>
                  prev.filter((m) => m.id !== optimisticId)
                )
                setStreamingToken('')
                setIsStreaming(false)
                setIsPending(false)
                queryClient.invalidateQueries({
                  queryKey: ['chat-session-messages', sessionId],
                })
                queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
              } else if (eventType === 'clarification_needed') {
                setClarification({
                  question: payload.question ?? '',
                  messageId: payload.message_id ?? '',
                })
                // Remove optimistic message, stop streaming indicator
                setOptimisticMessages((prev) =>
                  prev.filter((m) => m.id !== optimisticId)
                )
                setStreamingToken('')
                setIsStreaming(false)
                setIsPending(false)
              } else if (eventType === 'error') {
                throw new Error(payload.message ?? 'Stream error')
              }
            }
          }
        })
        .catch((err: unknown) => {
          if (err instanceof Error && err.name === 'AbortError') return

          // Remove optimistic message and clear streaming state
          setOptimisticMessages((prev) =>
            prev.filter((m) => m.id !== optimisticId)
          )
          setStreamingToken('')
          setIsStreaming(false)
          setIsPending(false)

          // Show toast (dynamic import to avoid SSR issues)
          import('sonner')
            .then(({ toast }) => {
              toast.error('Failed to send message. Please try again.')
            })
            .catch(() => {
              // ignore toast failure
            })
        })
    },
    [sessionId, queryClient]
  )

  return {
    send,
    isPending,
    streamingToken,
    isStreaming,
    optimisticMessages,
    clarification,
    dismissClarification,
  }
}
