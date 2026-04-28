'use client'
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
export function ChatLayout() {
  const { sessionId } = useSelectedSession()
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

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col bg-background md:h-screen">
      <MessageThread
        sessionId={sessionId}
        streamingToken={streamingToken}
        isStreaming={isStreaming}
        extraMessages={optimisticMessages}
        onSend={send}
      />
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
