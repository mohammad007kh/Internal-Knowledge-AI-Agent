'use client'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { MessageSquarePlusIcon, SparklesIcon } from 'lucide-react'
import { useCallback } from 'react'
import { ChatInputBar } from './ChatInputBar'
import { ClarificationCard } from './ClarificationCard'
import { GuardrailCard } from './GuardrailCard'
import { MessageThread } from './MessageThread'
import { useSelectedSession } from './SelectedSessionContext'
import { useChat } from './useChat'

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
interface ChatLayoutProps {
  /**
   * Initial sessionId, threaded straight from a server-component page's
   * `params` so SSR renders the correct surface on the very first paint
   * (no flicker between empty-hero and message-thread on hard refresh).
   *
   * When omitted (e.g. `/chat` with no segment), falls back to the URL-
   * derived value from `useSelectedSession()`.  The context remains the
   * authority for `setSessionId` / `abortStream` on every code path —
   * this prop only seeds the initial render.
   */
  sessionId?: string
}

export function ChatLayout({ sessionId: propSessionId }: ChatLayoutProps = {}) {
  const { sessionId: ctxSessionId, setSessionId } = useSelectedSession()
  const sessionId = propSessionId ?? ctxSessionId
  const {
    send,
    abort,
    isPending,
    isPendingNewSession,
    streamingToken,
    isStreaming,
    optimisticMessages,
    clarification,
    dismissClarification,
    guardrailMessage,
    dismissGuardrail,
    activityLog,
    lastMessageId,
  } = useChat({ sessionId })

  // U15 lazy creation: `send` is now safe to call with a null `sessionId`.
  // The hook routes the request to the `'new'` sentinel, and the backend
  // creates the row inline and announces its real UUID via
  // `event: session_created`. The hook handles the URL swap and cache
  // patching internally, so this component just hands off the text.
  const handleSend = useCallback(
    (text: string) => {
      if (!text.trim()) return
      send(text)
    },
    [send]
  )

  // The hero "Start a new chat" button is now a pure navigation: the row
  // doesn't exist until the user types and sends, so all this does is
  // ensure the URL is `/chat` (clearing any prior session selection).
  // Using `replace` so the empty-state surface doesn't leave a history
  // entry between the previously-selected chat and the next one created
  // on first send.
  const handleStartNewChat = useCallback(() => {
    setSessionId(null, { replace: true })
  }, [setSessionId])

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
            <Button type="button" size="lg" className="mt-2 gap-2" onClick={handleStartNewChat}>
              <MessageSquarePlusIcon className="h-4 w-4" aria-hidden />
              Start a new chat
            </Button>
          </Card>
        </div>
      ) : (
        <MessageThread
          sessionId={sessionId}
          streamingToken={streamingToken}
          isStreaming={isStreaming}
          isPending={isPending}
          extraMessages={optimisticMessages}
          onSend={handleSend}
          activityLog={activityLog}
          finishedMessageId={lastMessageId}
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
        // `isPending && !isStreaming` covers the steady-state brief window
        // between submit and the first SSE frame. `isPendingNewSession` is
        // the U15 lazy-create gate that stays latched from a null-session
        // submit until the `event: session_created` SSE frame lands — without
        // it, a double-Enter during the assistant's first-token stream would
        // re-enable the send button and fire a SECOND
        // POST /sessions/new/messages, creating a second orphan row.
        disabled={(isPending && !isStreaming) || isPendingNewSession}
        isStreaming={isStreaming}
        sessionId={sessionId}
        allowEmptySession
      />
    </div>
  )
}
