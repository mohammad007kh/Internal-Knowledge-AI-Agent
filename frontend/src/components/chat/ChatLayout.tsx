'use client'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { apiClient } from '@/lib/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MessageSquarePlusIcon, SparklesIcon } from 'lucide-react'
import { useCallback } from 'react'
import { toast } from 'sonner'
import { ChatInputBar } from './ChatInputBar'
import { ClarificationCard } from './ClarificationCard'
import { GuardrailCard } from './GuardrailCard'
import { MessageThread } from './MessageThread'
import { useSelectedSession } from './SelectedSessionContext'
import { useChat } from './useChat'

interface CreatedSession {
  id: string
  title: string
}

/**
 * Single-pane chat surface.
 *
 * The previous 3-column layout (app sidebar | sessions rail | chat) wasted
 * ~280px on a sessions list that was empty for first-time users and
 * duplicated chrome on every viewport. Sessions now live in the user shell
 * sidebar (`<ChatSidebarGroup>`) with a slide-over panel for the full list,
 * which mirrors the ChatGPT/Claude.ai mental model and gives the message
 * canvas full width.
 */
export function ChatLayout() {
  const { sessionId, setSessionId } = useSelectedSession()
  const queryClient = useQueryClient()
  const {
    send,
    abort,
    isPending,
    streamingToken,
    isStreaming,
    optimisticMessages,
    clarification,
    dismissClarification,
    guardrailMessage,
    dismissGuardrail,
  } = useChat({ sessionId })

  const createMutation = useMutation({
    mutationFn: async (): Promise<CreatedSession> => {
      const res = await apiClient.post<CreatedSession>('/api/v1/chat/sessions', {
        title: 'New chat',
      })
      return res.data
    },
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ['chat-sessions'] })
      setSessionId(session.id)
    },
    onError: () => toast.error('Failed to create session.'),
  })

  // Single source of truth for "make sure a session exists, then return its
  // id". Used by both the hero "Start a new chat" button (which triggers it
  // directly) and the input-bar send path (which uses it to auto-create
  // when the user types a message before any session is selected). Reuses
  // the existing mutation — no new API call is introduced.
  const ensureSession = useCallback(async (): Promise<string> => {
    if (sessionId) return sessionId
    const created = await createMutation.mutateAsync()
    return created.id
  }, [sessionId, createMutation])

  // Send wrapper: when no session is selected, create one first and then
  // dispatch the message into the freshly-created session in the same tick
  // (via `useChat.send`'s `overrideSessionId` argument).  See the matching
  // exception in useChat's session-switch abort effect — without it, the
  // cleanup that fires on null → newId would cancel the just-started SSE
  // stream and reset the surface to the empty state.
  const handleSend = useCallback(
    async (text: string) => {
      if (!text.trim()) return
      if (sessionId) {
        send(text)
        return
      }
      try {
        const newId = await ensureSession()
        send(text, newId)
      } catch {
        // The mutation's onError already surfaces a toast; swallow here so
        // an unhandled promise rejection does not bubble out of the input.
      }
    },
    [sessionId, send, ensureSession]
  )

  const handleStartNewChat = useCallback(() => {
    if (createMutation.isPending) return
    createMutation.mutate()
  }, [createMutation])

  // First-time canvas: replace the muted "Select or create a session" line
  // with a centered hero + prominent primary CTA so new users have an
  // unambiguous next step. The sidebar "+" still works for power users.
  // We leave the hero up while the user is composing (no optimistic message,
  // no stream) so the auto-create-on-send flow takes over the moment they
  // submit — at that point the optimistic bubble flips us into the thread.
  const showEmptyHero = !sessionId && optimisticMessages.length === 0 && !isStreaming

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col bg-background md:h-screen">
      {showEmptyHero ? (
        <div className="flex flex-1 items-center justify-center px-4">
          <Card className="flex w-full max-w-md flex-col items-center gap-4 p-8 text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
              <SparklesIcon className="h-7 w-7 text-primary" aria-hidden />
            </div>
            <div className="space-y-1.5">
              <h2 className="text-xl font-semibold tracking-tight">
                Ask your knowledge base anything
              </h2>
              <p className="text-sm text-muted-foreground">
                Start a conversation grounded in your indexed sources.
              </p>
            </div>
            <Button
              type="button"
              size="lg"
              className="mt-2 gap-2"
              disabled={createMutation.isPending}
              onClick={handleStartNewChat}
            >
              <MessageSquarePlusIcon className="h-4 w-4" aria-hidden />
              {createMutation.isPending ? 'Creating…' : 'Start a new chat'}
            </Button>
          </Card>
        </div>
      ) : (
        <MessageThread
          sessionId={sessionId}
          streamingToken={streamingToken}
          isStreaming={isStreaming}
          extraMessages={optimisticMessages}
          onSend={handleSend}
        />
      )}
      {clarification && (
        <ClarificationCard
          question={clarification.question}
          onDismiss={dismissClarification}
          onReply={(answer) => handleSend(answer)}
          disabled={isPending}
        />
      )}
      {guardrailMessage && (
        <GuardrailCard message={guardrailMessage} onDismiss={dismissGuardrail} />
      )}
      <ChatInputBar
        onSend={handleSend}
        onStop={abort}
        disabled={(isPending && !isStreaming) || createMutation.isPending}
        isStreaming={isStreaming}
        sessionId={sessionId}
        isCreatingSession={createMutation.isPending}
        allowEmptySession
      />
    </div>
  )
}
