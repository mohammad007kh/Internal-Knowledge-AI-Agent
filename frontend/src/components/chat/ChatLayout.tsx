'use client'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { apiClient } from '@/lib/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { MessageSquarePlusIcon, SparklesIcon } from 'lucide-react'
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

  // First-time canvas: replace the muted "Select or create a session" line
  // with a centered hero + prominent primary CTA so new users have an
  // unambiguous next step. The sidebar "+" still works for power users.
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
              size="lg"
              className="mt-2 gap-2"
              disabled={createMutation.isPending}
              onClick={() => createMutation.mutate()}
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
          onSend={send}
        />
      )}
      {clarification && (
        <ClarificationCard
          question={clarification.question}
          onDismiss={dismissClarification}
          onReply={(answer) => send(answer)}
          disabled={isPending}
        />
      )}
      {guardrailMessage && (
        <GuardrailCard message={guardrailMessage} onDismiss={dismissGuardrail} />
      )}
      <ChatInputBar
        onSend={send}
        onStop={abort}
        disabled={isPending && !isStreaming}
        isStreaming={isStreaming}
        sessionId={sessionId}
      />
    </div>
  )
}
