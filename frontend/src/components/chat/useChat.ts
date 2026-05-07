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

/**
 * Minimal shape of the `['chat-sessions']` React Query cache used for the
 * optimistic title patch. Mirrors `SessionsResponse` in `SessionList.tsx`
 * and `ChatSidebarGroup.tsx` — kept loose here because we only touch the
 * `id`/`title` fields of each item and don't want to drag in the full
 * ChatSession type for an internal cache update.
 */
interface SessionsListSnapshot {
  // Matches ChatSessionListResponse on the wire (backend/src/schemas/chat.py)
  // — `sessions`, not `items`. Renamed from `items` in commit ebb9abd to
  // align frontend cache with the actual response shape.
  sessions: Array<{ id: string; title: string; [key: string]: unknown }>
  total: number
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
  // Capture the session id used at send-time. If the original send auto-created
  // a session and React hadn't committed `setSessionId` yet, retrying with the
  // closure's `sessionId` would target `null` and silently no-op. Persisting
  // the id here lets the retry closure pass it as `overrideSessionId`.
  const lastSessionIdRef = useRef<string | null>(null)
  const sendRef = useRef<(text: string, overrideSessionId?: string) => void>(() => {})
  // Tracks whether a terminal signal (lastMessageId/clarification/guardrail/error)
  // has already cleaned up `isPending` and the optimistic bubble for the current
  // send. The stream-end watcher uses this to detect zombies, and `.finally()`
  // on `sendMessage` uses it to avoid double-clearing state.
  const settledRef = useRef<boolean>(true)
  // Track previous `isStreaming` so the stream-end watcher can detect a
  // false→true→false cycle without ever observing a terminal frame.
  const prevIsStreamingRef = useRef<boolean>(false)

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
      lastSessionIdRef.current = targetSessionId

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
      settledRef.current = false

      stream
        .sendMessage(targetSessionId, trimmed, [])
        .catch(() => {
          clearOptimistic()
          setIsPending(false)
          settledRef.current = true
          import('sonner')
            .then(({ toast }) => {
              toast.error('Failed to send message. Please try again.', {
                action: {
                  label: 'Retry',
                  onClick: () =>
                    sendRef.current(lastQueryRef.current, lastSessionIdRef.current ?? undefined),
                },
              })
            })
            .catch(() => {})
        })
        .finally(() => {
          // Graceful-close-without-`done` resolves the promise without ever
          // delivering a terminal event, so `.catch` never fires. Without
          // `.finally`, `isPending` would stay true and the textarea would
          // stay locked. Skip if a terminal-event handler already cleared.
          if (!settledRef.current) {
            // Defensive: if the stream-end watcher hasn't run yet (rare
            // microtask vs effect ordering edge case), make sure neither the
            // optimistic bubble nor isPending leaks across the close.
            clearOptimistic()
            setIsPending(false)
          }
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
    // Mark settled so the stream-end watcher (which fires on isStreaming
    // false→true→false) doesn't read this intentional abort as a "connection
    // dropped" event and toast the user a spurious "Connection lost" message.
    settledRef.current = true
  }, [stream, clearOptimistic])

  // Abort any in-flight stream when the active session changes — switching
  // sessions (including deletion of the current one) must not leak a stream
  // that would then populate the wrong session's view on completion.
  //
  // EXCEPTION: skip the abort when this render's sessionId is `null`.
  // That cleanup will fire on the null → newId transition (auto-create-on-send
  // landing a freshly-created id), and the stream that was just started is
  // bound to the new id — aborting here cancels its AbortController and
  // clears the optimistic bubble, which is exactly the regression we are
  // fixing. The cleanup closes over `sessionId` from this render, so the
  // decision is based on the id we are leaving, not the one we are entering.
  // biome-ignore lint/correctness/useExhaustiveDependencies: only session switches should trigger this
  useEffect(() => {
    return () => {
      // Only abort when leaving a real (non-null) session. A null → newId
      // transition runs this cleanup with the captured `sessionId === null`
      // and must NOT abort, because the freshly-started stream belongs to
      // the new session, not the (non-existent) previous one.
      if (sessionId !== null) {
        abort()
      }
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
    settledRef.current = true
  }, [stream.messageType, stream.clarificationQuestion, stream.lastMessageId, clearOptimistic])

  useEffect(() => {
    if (stream.messageType !== 'guardrail_blocked') return
    if (!stream.guardrailMessage) return
    setLocalGuardrail(stream.guardrailMessage)
    clearOptimistic()
    setIsPending(false)
    settledRef.current = true
  }, [stream.messageType, stream.guardrailMessage, clearOptimistic])

  useEffect(() => {
    if (stream.messageType !== 'error') return
    clearOptimistic()
    setIsPending(false)
    settledRef.current = true
    const msg = stream.errorMessage ?? 'Stream error'
    import('sonner')
      .then(({ toast }) => {
        toast.error(msg, {
          action: {
            label: 'Retry',
            onClick: () =>
              sendRef.current(lastQueryRef.current, lastSessionIdRef.current ?? undefined),
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
    settledRef.current = true

    if (sessionId) {
      queryClient.invalidateQueries({
        queryKey: ['chat-session-messages', sessionId],
      })
    }
    queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
  }, [stream.lastMessageId, sessionId, queryClient, clearOptimistic])

  // Stream-end watcher: when `isStreaming` flips true→false without any
  // terminal frame having marked the send as settled, the send is a zombie
  // (server connection died mid-flight, no `done`/`error`/`clarification`/
  // `guardrail` ever arrived). Surface a toast + error state so the existing
  // retry path takes over and the thinking-dots bubble doesn't pulse forever.
  useEffect(() => {
    const wasStreaming = prevIsStreamingRef.current
    prevIsStreamingRef.current = stream.isStreaming
    if (!(wasStreaming && !stream.isStreaming)) return
    if (settledRef.current) return
    // No terminal signal observed — treat as a connection drop.
    settledRef.current = true
    clearOptimistic()
    setIsPending(false)
    import('sonner')
      .then(({ toast }) => {
        toast.error('Connection lost — please retry.', {
          action: {
            label: 'Retry',
            onClick: () =>
              sendRef.current(lastQueryRef.current, lastSessionIdRef.current ?? undefined),
          },
        })
      })
      .catch(() => {})
  }, [stream.isStreaming, clearOptimistic])

  // Auto-titling: when the backend emits an SSE `title` frame on the first
  // user turn, optimistically patch the chat-sessions list cache so the
  // sidebar updates immediately. The backend has already PATCHed the title
  // via the repo before emitting this frame, so the DB is canonical; this
  // path only avoids the visual lag of waiting for the next list refetch.
  //
  // Cache shape: backend returns ChatSessionListResponse = {sessions, total}
  // (renamed from items in commit ebb9abd to match the wire). Manual-rename
  // guard accepts all 3 placeholder titles in the codebase ('New chat',
  // 'New Chat', 'New conversation') — same set the backend's auto-title
  // gate accepts — so a manually-renamed title in any form is preserved.
  useEffect(() => {
    const newTitle = stream.lastTitle
    if (!newTitle || !sessionId) return
    const PLACEHOLDERS = new Set(['New chat', 'New Chat', 'New conversation'])
    queryClient.setQueryData<SessionsListSnapshot>(['chat-sessions'], (prev) => {
      if (!prev) return prev
      const cached = prev.sessions.find((s) => s.id === sessionId)
      if (!cached || !PLACEHOLDERS.has(cached.title)) return prev
      return {
        ...prev,
        sessions: prev.sessions.map((s) => (s.id === sessionId ? { ...s, title: newTitle } : s)),
      }
    })
    queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
  }, [stream.lastTitle, sessionId, queryClient])

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
