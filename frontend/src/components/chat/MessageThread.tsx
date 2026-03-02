'use client'

import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useQuery } from '@tanstack/react-query'
import { BotIcon, UserIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { CitationPanel } from './CitationPanel'
import { FeedbackButtons } from './FeedbackButtons'
import type { Citation, Message, SessionMessagesResponse } from './types'

interface MessageThreadProps {
  sessionId: string | null
  streamingToken?: string
  isStreaming?: boolean
  extraMessages?: Message[]
}

async function fetchMessages(id: string): Promise<SessionMessagesResponse> {
  const res = await apiClient.get<SessionMessagesResponse>(`/chat/sessions/${id}`)
  return res.data
}

export function MessageThread({
  sessionId,
  streamingToken = '',
  isStreaming = false,
  extraMessages = [],
}: MessageThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const [openCitation, setOpenCitation] = useState<Citation | null>(null)

  const { data } = useQuery({
    queryKey: ['chat-session-messages', sessionId],
    queryFn: () => fetchMessages(sessionId as string),
    enabled: !!sessionId,
    staleTime: 5_000,
  })

  const persisted: Message[] = data?.messages ?? []
  const allMessages: Message[] = [...persisted, ...extraMessages]

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll on message count or token change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [allMessages.length, streamingToken])

  if (!sessionId) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">
          Select or create a session to start chatting.
        </p>
      </div>
    )
  }

  return (
    <>
      <div
        className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4"
        role="log"
        aria-live="polite"
        aria-label="Conversation"
      >
        {allMessages.length === 0 && !isStreaming && (
          <p className="mt-8 text-center text-sm text-muted-foreground">
            No messages yet. Ask a question below.
          </p>
        )}

        {allMessages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            sessionId={sessionId ?? ''}
            onCitationClick={setOpenCitation}
          />
        ))}

        {isStreaming && (
          <div className="flex items-start gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted">
              <BotIcon className="h-4 w-4 text-muted-foreground" />
            </div>
            <div className="max-w-[75%] rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5">
              <p className="whitespace-pre-wrap break-words text-sm">
                {streamingToken}
                <span
                  className="ml-0.5 inline-block h-3.5 w-0.5 bg-foreground align-middle"
                  aria-hidden="true"
                />
              </p>
            </div>
          </div>
        )}

        <div ref={bottomRef} aria-hidden="true" />
      </div>

      <CitationPanel citation={openCitation} onClose={() => setOpenCitation(null)} />
    </>
  )
}

interface MessageBubbleProps {
  message: Message
  sessionId: string
  onCitationClick: (c: Citation) => void
}

function MessageBubble({ message, sessionId, onCitationClick }: MessageBubbleProps) {
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex items-start gap-3', isUser && 'flex-row-reverse')}>
      <div
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
          isUser ? 'bg-primary' : 'bg-muted'
        )}
        aria-hidden="true"
      >
        {isUser ? (
          <UserIcon className="h-4 w-4 text-primary-foreground" />
        ) : (
          <BotIcon className="h-4 w-4 text-muted-foreground" />
        )}
      </div>

      <div
        className={cn(
          'max-w-[75%] rounded-2xl px-4 py-2.5',
          isUser ? 'rounded-tr-sm bg-primary text-primary-foreground' : 'rounded-tl-sm bg-muted'
        )}
      >
        <p className="whitespace-pre-wrap break-words text-sm">{message.content}</p>

        {!isUser && message.citations && message.citations.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5" role="list" aria-label="Citations">
            {message.citations.map((c, idx) => (
              <button
                key={c.id}
                className={cn(
                  'inline-flex h-5 w-5 items-center justify-center rounded-full',
                  'bg-background/60 text-[10px] font-medium text-foreground',
                  'hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
                )}
                onClick={() => onCitationClick(c)}
                aria-label={`View citation ${idx + 1}: ${c.document_title}`}
                type="button"
              >
                {idx + 1}
              </button>
            ))}
          </div>
        )}

        {!isUser && (
          <FeedbackButtons
            sessionId={sessionId}
            messageId={message.id}
            initialRating={message.feedback?.rating ?? null}
          />
        )}

        <time
          className={cn(
            'mt-1 block text-[10px]',
            isUser ? 'text-primary-foreground/70' : 'text-muted-foreground'
          )}
          dateTime={message.created_at}
          aria-label={new Date(message.created_at).toLocaleString()}
        >
          {new Date(message.created_at).toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </time>
      </div>
    </div>
  )
}
