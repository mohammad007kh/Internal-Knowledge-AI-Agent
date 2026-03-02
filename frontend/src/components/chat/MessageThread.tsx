'use client'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

interface SessionWithMessages {
  session: { id: string; title: string }
  messages: Message[]
}

interface MessageThreadProps {
  sessionId: string | null
  streamingToken?: string
  isStreaming?: boolean
  extraMessages?: Message[]
}

async function fetchSession(id: string): Promise<SessionWithMessages> {
  const res = await apiClient.get(`/chat/sessions/${id}`)
  return res.data
}

export function MessageThread({
  sessionId,
  streamingToken = '',
  isStreaming = false,
  extraMessages = [],
}: MessageThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data } = useQuery({
    queryKey: ['chat-session-messages', sessionId],
    queryFn: () => fetchSession(sessionId as string),
    enabled: !!sessionId,
    staleTime: 5_000,
  })

  const persistedMessages: Message[] = data?.messages ?? []
  const allMessages = [...persistedMessages, ...extraMessages]

  // biome-ignore lint/correctness/useExhaustiveDependencies: intentionally scroll on count+token only
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'instant' })
  }, [allMessages.length, streamingToken])

  if (!sessionId) {
    return (
      <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm">
        Select a session or start a new chat.
      </div>
    )
  }

  return (
    <div
      className="flex flex-1 flex-col overflow-y-auto px-4 py-4 space-y-4"
      aria-live="polite"
      aria-label="Chat messages"
    >
      {allMessages.length === 0 && !isStreaming ? (
        <div className="flex flex-1 items-center justify-center text-muted-foreground text-sm">
          Start a conversation.
        </div>
      ) : (
        allMessages.map((msg) => <MessageBubble key={msg.id} message={msg} />)
      )}
      {isStreaming && (
        <div className="flex justify-start">
          <div
            className={cn(
              'max-w-[75%] rounded-2xl px-4 py-2.5 text-sm',
              'bg-muted text-muted-foreground'
            )}
            aria-live="polite"
            aria-label="Assistant is typing"
          >
            {streamingToken || (
              <span className="inline-block h-4 w-4 animate-pulse rounded-full bg-current opacity-50" />
            )}
            {streamingToken && (
              <span className="ml-0.5 inline-block h-3.5 w-0.5 bg-current opacity-75" />
            )}
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === 'user'
  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[75%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap break-words',
          isUser ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
        )}
      >
        {message.content}
      </div>
    </div>
  )
}
