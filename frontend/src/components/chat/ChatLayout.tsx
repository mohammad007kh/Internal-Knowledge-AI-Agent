'use client'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import { ChatInputBar } from './ChatInputBar'
import { ClarificationCard } from './ClarificationCard'
import { GuardrailCard } from './GuardrailCard'
import { MessageThread } from './MessageThread'
import { useSelectedSession } from './SelectedSessionContext'
import { SessionList } from './SessionList'
import { useChat } from './useChat'

export function ChatLayout() {
  const { sessionId } = useSelectedSession()
  const isDesktop = useMediaQuery('(min-width: 768px)')
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

  const chatPane = (
    <div className="flex flex-1 flex-col overflow-hidden">
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

  if (isDesktop) {
    return (
      <div className="grid h-[calc(100vh-4rem)] grid-cols-[280px_1fr] divide-x divide-border bg-background">
        <aside className="flex flex-col overflow-hidden">
          <SessionList />
        </aside>
        <main className="flex flex-col overflow-hidden">{chatPane}</main>
      </div>
    )
  }

  return (
    <div className="flex h-[calc(100vh-4rem)] flex-col">
      <Tabs defaultValue="chat" className="flex flex-1 flex-col overflow-hidden">
        <TabsList className="mx-4 mt-2 shrink-0">
          <TabsTrigger value="sessions" className="flex-1">
            Sessions
          </TabsTrigger>
          <TabsTrigger value="chat" className="flex-1">
            Chat
          </TabsTrigger>
        </TabsList>
        <TabsContent
          value="sessions"
          className="flex-1 overflow-hidden data-[state=inactive]:hidden"
        >
          <SessionList />
        </TabsContent>
        <TabsContent
          value="chat"
          className="flex flex-1 flex-col overflow-hidden data-[state=inactive]:hidden"
        >
          {chatPane}
        </TabsContent>
      </Tabs>
    </div>
  )
}
