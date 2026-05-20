'use client'

/**
 * Test tab — admin-only sandbox chat scoped to a single source.
 *
 * State is `useState`-only by design. Browser refresh wipes everything,
 * navigating away wipes everything. The product wants this: the tab is a
 * verification surface, not a workspace. Users would otherwise feel cheated
 * that real chats they sent here don't show up in /chat history.
 *
 * The SSE consumer (`useSandboxStream`) uses the same event grammar as the
 * persistent chat, so behavior on `delta` / `error` / `clarification` /
 * `done` matches what users see in production.
 */
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useAuth } from '@/features/auth/context/AuthContext'
import type { SourceDetail } from '@/lib/api/sources'
import { cn } from '@/lib/utils'
import {
  AlertTriangleIcon,
  BotIcon,
  CircleAlertIcon,
  InfoIcon,
  LockIcon,
  RefreshCwIcon,
  SendHorizontalIcon,
  SparklesIcon,
  SquareIcon,
  UserIcon,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { sourceKindOf } from './sourceTypeMatrix'
import { useSandboxStream } from './useSandboxStream'

interface TestTabProps {
  source: SourceDetail
}

interface SandboxMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
}

const HISTORY_TURN_CAP = 20

/**
 * Hard-coded starter prompts per source kind. Intentionally NOT
 * LLM-generated — these are debug affordances, not product copy.
 */
function starterPromptsFor(source: SourceDetail): ReadonlyArray<string> {
  const kind = sourceKindOf(source.source_type)
  if (kind === 'database') {
    return [
      'What tables exist in this source?',
      'Describe the schema in plain English.',
      'What is the most recently updated row in any table?',
    ]
  }
  if (kind === 'file') {
    return [
      'Summarize the most recent document.',
      'What are the key topics covered across these files?',
      'Find any mention of deadlines or dates.',
    ]
  }
  // web + connector
  return [
    "What's the most recent page about?",
    'Give me a 3-bullet summary of this source.',
    'What does this source say about onboarding?',
  ]
}

export function TestTab({ source }: TestTabProps) {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  if (!isAdmin) {
    return (
      <div
        role="alert"
        className="flex items-start gap-3 rounded-md border border-amber-500/40 bg-amber-500/5 p-4 text-sm text-amber-900 dark:text-amber-200"
      >
        <LockIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <div>
          <p className="font-medium">Test mode is admin-only</p>
          <p className="text-xs opacity-90">
            Only administrators can run sandbox queries against an unpublished source.
          </p>
        </div>
      </div>
    )
  }

  return <TestTabBody source={source} />
}

interface TestTabBodyProps {
  source: SourceDetail
}

function TestTabBody({ source }: TestTabBodyProps) {
  const stream = useSandboxStream()
  const [messages, setMessages] = useState<SandboxMessage[]>([])
  const [input, setInput] = useState('')
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const schemaFailed =
    sourceKindOf(source.source_type) === 'database' && source.schema_status === 'FAILED'
  const inputDisabled = stream.isStreaming || schemaFailed

  // When the assistant turn finishes, fold the streamed text into the
  // messages array as a real "assistant" message and clear the stream
  // buffer so the next send starts clean.
  useEffect(() => {
    if (stream.isStreaming) return
    if (stream.isPending) return
    if (stream.messageType === 'normal' && stream.currentResponse.length > 0) {
      // Append the assistant turn and reset stream state.
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}`,
          role: 'assistant',
          content: stream.currentResponse,
        },
      ])
      stream.reset()
      return
    }
    if (stream.messageType === 'error' && stream.errorMessage) {
      setMessages((prev) => [
        ...prev,
        {
          id: `e-${Date.now()}`,
          role: 'assistant',
          content: `_Stream error:_ ${stream.errorMessage}`,
        },
      ])
      stream.reset()
      return
    }
    if (stream.messageType === 'guardrail_blocked' && stream.guardrailMessage) {
      setMessages((prev) => [
        ...prev,
        {
          id: `g-${Date.now()}`,
          role: 'assistant',
          content: `_Blocked by policy:_ ${stream.guardrailMessage}`,
        },
      ])
      stream.reset()
      return
    }
    if (stream.messageType === 'clarification' && stream.clarificationQuestion) {
      setMessages((prev) => [
        ...prev,
        {
          id: `c-${Date.now()}`,
          role: 'assistant',
          content: `_Clarification needed:_ ${stream.clarificationQuestion}`,
        },
      ])
      stream.reset()
      return
    }
    // biome-ignore lint/correctness/useExhaustiveDependencies: stream is a stable ref
  }, [
    stream.isStreaming,
    stream.isPending,
    stream.messageType,
    stream.currentResponse,
    stream.errorMessage,
    stream.guardrailMessage,
    stream.clarificationQuestion,
  ])

  // Auto-scroll to bottom on new turns / streaming tokens.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, stream.currentResponse])

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim()
      if (!trimmed || stream.isStreaming) return
      const next: SandboxMessage = {
        id: `u-${Date.now()}`,
        role: 'user',
        content: trimmed,
      }
      // Capture history (excluding the just-added user turn — backend treats
      // the new query separately).
      const history = messages
        .slice(-HISTORY_TURN_CAP)
        .map((m) => ({ role: m.role, content: m.content }))
      setMessages((prev) => [...prev, next])
      setInput('')
      void stream.sendMessage(source.id, trimmed, history)
    },
    [messages, source.id, stream]
  )

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send(input)
    }
  }

  const starters = useMemo(() => starterPromptsFor(source), [source])

  return (
    <div className="space-y-3">
      {/* Banner — neutral info color */}
      <div
        className="flex items-start gap-3 rounded-md border border-blue-500/30 bg-blue-500/5 p-3 text-sm text-blue-900 dark:text-blue-200"
        role="note"
        data-testid="sandbox-banner"
      >
        <InfoIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
        <p>
          <strong>This is a one-off conversation.</strong> Messages here aren&apos;t saved to
          history and disappear when you leave or refresh the page. Use it to verify retrieval,
          citations, and answer quality before approving the source for users.
        </p>
      </div>

      <SourceStateWarnings source={source} />

      <div className="flex flex-col rounded-md border bg-card">
        <div
          className="flex max-h-[60vh] min-h-[280px] flex-col gap-3 overflow-y-auto p-4"
          role="log"
          aria-live="polite"
          aria-label="Sandbox conversation"
        >
          {messages.length === 0 && !stream.isStreaming && !stream.isPending ? (
            <SandboxEmptyState
              starters={starters}
              onStarterClick={(p) => send(p)}
              disabled={inputDisabled}
            />
          ) : null}

          {messages.map((m) => (
            <SandboxBubble key={m.id} message={m} />
          ))}

          {(stream.isStreaming || stream.isPending) && (
            <div className="flex items-start gap-3">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted">
                <BotIcon className="h-4 w-4 text-muted-foreground" />
              </div>
              <div className="max-w-[75%] rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5">
                {stream.currentResponse.length > 0 ? (
                  <div className="whitespace-pre-wrap break-words text-sm">
                    {stream.currentResponse}
                    <span
                      className="ml-0.5 inline-block h-3.5 w-0.5 bg-foreground align-middle"
                      aria-hidden="true"
                    />
                  </div>
                ) : (
                  <div
                    className="flex items-center gap-1 py-0.5"
                    role="status"
                    aria-label="Assistant is thinking"
                    data-testid="sandbox-thinking"
                  >
                    <span
                      className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/40"
                      aria-hidden
                    />
                    <span
                      className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/40"
                      style={{ animationDelay: '150ms' }}
                      aria-hidden
                    />
                    <span
                      className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/40"
                      style={{ animationDelay: '300ms' }}
                      aria-hidden
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          <div ref={bottomRef} aria-hidden />
        </div>

        <form
          className="flex items-end gap-2 border-t p-3"
          onSubmit={(e) => {
            e.preventDefault()
            if (stream.isStreaming) {
              stream.abort()
            } else {
              send(input)
            }
          }}
          aria-label="Sandbox chat input"
        >
          <Textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              schemaFailed
                ? 'Schema study failed — fix in Sync tab'
                : stream.isStreaming
                  ? 'Generating… press Esc to stop'
                  : 'Ask a question against this source… (Enter to send)'
            }
            className={cn('max-h-32 min-h-[2.5rem] flex-1 resize-none rounded-xl')}
            rows={1}
            maxLength={4000}
            disabled={inputDisabled}
            aria-label="Sandbox message input"
            data-testid="sandbox-input"
          />
          {stream.isStreaming ? (
            <Button
              type="button"
              size="icon"
              variant="destructive"
              onClick={stream.abort}
              aria-label="Stop sandbox generation"
              className="shrink-0"
            >
              <SquareIcon className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              type="submit"
              size="icon"
              disabled={!input.trim() || inputDisabled}
              aria-label="Send sandbox message"
              className="shrink-0"
              data-testid="sandbox-send"
            >
              <SendHorizontalIcon className="h-4 w-4" />
            </Button>
          )}
        </form>
      </div>

      {messages.length > 0 && (
        <div className="flex justify-end">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setMessages([])}
            disabled={stream.isStreaming}
            data-testid="sandbox-clear"
          >
            <RefreshCwIcon className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            Clear conversation
          </Button>
        </div>
      )}
    </div>
  )
}

interface SandboxEmptyStateProps {
  starters: ReadonlyArray<string>
  onStarterClick: (prompt: string) => void
  disabled: boolean
}

function SandboxEmptyState({ starters, onStarterClick, disabled }: SandboxEmptyStateProps) {
  return (
    <div
      className="mx-auto mt-6 max-w-md space-y-4 text-center"
      data-testid="sandbox-empty-state"
    >
      <SparklesIcon className="mx-auto h-10 w-10 text-primary/40" aria-hidden />
      <h3 className="text-base font-semibold">Try a question against this source</h3>
      <div className="grid gap-2 pt-2">
        {starters.map((p) => (
          <button
            key={p}
            type="button"
            disabled={disabled}
            onClick={() => onStarterClick(p)}
            className="rounded-lg border border-border bg-card px-4 py-2.5 text-left text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="sandbox-starter"
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  )
}

function SandboxBubble({ message }: { message: SandboxMessage }) {
  const isUser = message.role === 'user'
  return (
    <div className={cn('flex items-start gap-3', isUser && 'flex-row-reverse')}>
      <div
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full',
          isUser ? 'bg-primary' : 'bg-muted'
        )}
        aria-hidden
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
          isUser
            ? 'rounded-tr-sm bg-primary text-primary-foreground'
            : 'rounded-tl-sm bg-muted'
        )}
      >
        <p className="whitespace-pre-wrap break-words text-sm">{message.content}</p>
      </div>
    </div>
  )
}

interface SourceStateWarningsProps {
  source: SourceDetail
}

function SourceStateWarnings({ source }: SourceStateWarningsProps) {
  const warnings: Array<{ tone: 'red' | 'amber' | 'neutral'; text: string }> = []

  if (source.connection_status === 'failed') {
    warnings.push({
      tone: 'red',
      text: 'This source is currently marked unavailable. Testing here is safe.',
    })
  } else if (source.connection_status === 'degraded') {
    warnings.push({
      tone: 'amber',
      text: 'Recent failures — answers may use stale data.',
    })
  }

  if (
    sourceKindOf(source.source_type) === 'database' &&
    source.schema_status === 'FAILED'
  ) {
    warnings.push({
      tone: 'red',
      text: "Schema study failed — text-to-query won't work. Fix in Sync tab first.",
    })
  }

  if (!source.is_active) {
    warnings.push({
      tone: 'neutral',
      text: "This source isn't yet approved for users — you're testing it in admin-only mode.",
    })
  }

  if (warnings.length === 0) return null

  return (
    <div className="space-y-2" data-testid="sandbox-warnings">
      {warnings.map((w) => (
        <div
          key={w.text}
          role={w.tone === 'red' ? 'alert' : 'status'}
          data-tone={w.tone}
          className={cn(
            'flex items-start gap-3 rounded-md border p-3 text-xs',
            w.tone === 'red' && 'border-destructive/40 bg-destructive/5 text-destructive',
            w.tone === 'amber' &&
              'border-amber-500/40 bg-amber-500/5 text-amber-900 dark:text-amber-200',
            w.tone === 'neutral' && 'border-border bg-muted/30 text-muted-foreground'
          )}
        >
          {w.tone === 'red' ? (
            <CircleAlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          ) : w.tone === 'amber' ? (
            <AlertTriangleIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          ) : (
            <InfoIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          )}
          <p>{w.text}</p>
        </div>
      ))}
    </div>
  )
}
