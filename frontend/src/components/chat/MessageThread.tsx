'use client'

import { apiClient } from '@/lib/api-client'
import {
  type ActivityState,
  type StepActivityEntry,
  emptyActivityState,
  selectActiveStep,
  selectLatestBudget,
} from '@/lib/sse/agent-events'
import { cn } from '@/lib/utils'
import { useQuery } from '@tanstack/react-query'
import { BotIcon, CopyIcon, InfoIcon, SparklesIcon, UserIcon } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { AgenticTurnFooter } from './AgenticTurnFooter'
import { DetailPanel, type PanelContent } from './CitationPanel'
import { KEEP_SEARCHING_PROMPT } from './ContinueSearchAffordance'
import { FeedbackButtons } from './FeedbackButtons'
import { MarkdownLite } from './MarkdownLite'
import { StatusLine } from './StatusLine'
import type { Citation, Message, SessionMessagesResponse } from './types'

interface MessageThreadProps {
  sessionId: string | null
  streamingToken?: string
  isStreaming?: boolean
  /**
   * True while a send is in flight — between user submit and either the first
   * SSE token (`isStreaming` flips true) or a terminal event. Used to show a
   * "thinking" bubble during the silent gap before the model emits tokens.
   */
  isPending?: boolean
  extraMessages?: Message[]
  onSend?: (text: string) => void
  /**
   * Per-turn agentic activity log for the in-flight turn. When it carries
   * plan/step content the in-flight indicator becomes the Layer-1 StatusLine;
   * otherwise the existing PulsingDots render unchanged (transitive flag-off
   * guard — an empty log means the agentic pipeline emitted nothing).
   */
  activityLog?: ActivityState
  /**
   * Assistant message id of the just-finished turn (from the stream's `done`
   * frame), or null mid-flight. Used to snapshot `activityLog` under the EXACT
   * turn — keying off the most-recent persisted message instead would
   * mis-attribute during the post-turn refetch window.
   */
  finishedMessageId?: string | null
}

const SUGGESTED_PROMPTS: string[] = [
  'Summarize the latest updates from my indexed sources.',
  'What are the most referenced documents this week?',
  'Draft a status update based on recent notes.',
]

async function fetchMessages(id: string): Promise<SessionMessagesResponse> {
  const res = await apiClient.get<SessionMessagesResponse>(`/api/v1/chat/sessions/${id}`)
  return res.data
}

export function MessageThread({
  sessionId,
  streamingToken = '',
  isStreaming = false,
  isPending = false,
  extraMessages = [],
  onSend,
  activityLog = emptyActivityState,
  finishedMessageId = null,
}: MessageThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [pinned, setPinned] = useState(true)
  // The right-side slide-over presents either a citation OR an agent step's
  // payload (T-073b generalization) — one panel, discriminated content.
  const [panel, setPanel] = useState<PanelContent | null>(null)
  // T-072: per-turn activity snapshots keyed by the assistant message id, so a
  // finished turn keeps its Layer-2 accordion after `activityLog` resets on the
  // next send. State (not a ref) so capturing a snapshot re-renders the turn
  // into showing its accordion. In-memory only → re-expand works for the LIVE
  // session; a hard reload starts empty (the rich log is stream-only).
  const [snapshots, setSnapshots] = useState<Map<string, ActivityState>>(() => new Map())
  // Turn ids where the user chose "Leave it here" on the budget-continue prompt.
  const [continueDismissed, setContinueDismissed] = useState<Set<string>>(() => new Set())

  const { data, error, isLoading } = useQuery({
    queryKey: ['chat-session-messages', sessionId],
    queryFn: () => fetchMessages(sessionId as string),
    enabled: !!sessionId,
    staleTime: 5_000,
    // Don't auto-retry a 404 — if the session doesn't exist or the user
    // doesn't have access, retrying just delays the not-found UX.
    retry: (failureCount, err) => {
      const status = (err as { response?: { status?: number } } | undefined)?.response?.status
      if (status === 404 || status === 403) return false
      return failureCount < 2
    },
  })

  const persisted: Message[] = data?.messages ?? []
  const allMessages: Message[] = [...persisted, ...extraMessages]
  const notFoundError = (error as { response?: { status?: number } } | null)?.response?.status
  const isMissingSession = notFoundError === 404 || notFoundError === 403

  // Only the most recent assistant turn may offer "Search again" — a follow-up
  // turn appends to the live edge, so offering it on a scrolled-up turn would
  // misrepresent what the click does.
  const lastAssistantId = [...allMessages].reverse().find((m) => m.role === 'assistant')?.id ?? null

  // T-072: when a turn finishes, snapshot the live activityLog under the
  // stream-provided assistant message id (NOT the most-recent persisted id,
  // which lags the post-turn refetch and would mis-attribute turn N's log to
  // turn N-1). The snapshot survives the next send's `activityLog` reset, so
  // the finished turn keeps its accordion for the rest of the session. The
  // once-guard lives inside the functional updater (returns `prev` unchanged →
  // React bails out, no re-render, no loop).
  useEffect(() => {
    if (isStreaming || !finishedMessageId || activityLog.entries.length === 0) return
    const turnId = finishedMessageId
    setSnapshots((prev) => (prev.has(turnId) ? prev : new Map(prev).set(turnId, activityLog)))
  }, [isStreaming, activityLog, finishedMessageId])

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const dist = el.scrollHeight - el.scrollTop - el.clientHeight
    setPinned(dist < 80)
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll when pinned and content grows
  useEffect(() => {
    if (pinned) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [allMessages.length, streamingToken, pinned])

  // U15 lazy creation: when the user has just sent the first message but
  // the backend hasn't yet emitted `event: session_created`, `sessionId`
  // is still null while `extraMessages` carries the optimistic user
  // bubble. Suppressing the thread here would flash the empty-state
  // helper text over the just-typed message. We fall through to the
  // normal thread render in that window so the bubble + thinking dots
  // remain visible.
  if (!sessionId && extraMessages.length === 0 && !isStreaming && !isPending) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-muted-foreground">
          Select or create a session to start chatting.
        </p>
      </div>
    )
  }

  // Backend rejected this session id (deleted, never existed, or not owned by
  // the current user).  Surface a clear empty state instead of leaving the
  // user in a phantom thread that silently fails on every send.
  if (isMissingSession) {
    return (
      <div className="flex flex-1 items-center justify-center px-4">
        <div className="max-w-sm space-y-3 text-center">
          <SparklesIcon className="mx-auto h-10 w-10 text-muted-foreground/40" aria-hidden />
          <h3 className="text-base font-semibold">Chat not found</h3>
          <p className="text-sm text-muted-foreground">
            This conversation doesn&apos;t exist or you don&apos;t have access. Pick another chat
            from the sidebar, or start a new one.
          </p>
          <a
            href="/chat"
            className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Back to chats
          </a>
        </div>
      </div>
    )
  }

  // First mount of a real session — show a thin shimmer instead of the
  // suggestion grid (which is meant for "you have no messages yet").
  // Don't intercept when a stream is actively running (the streaming bubble
  // is its own visual signal that work is in progress).
  if (isLoading && !isStreaming && persisted.length === 0 && extraMessages.length === 0) {
    return (
      <div className="flex flex-1 flex-col gap-4 px-4 py-4" aria-busy="true">
        <div className="h-12 animate-pulse rounded-lg bg-muted/40" />
        <div className="ml-auto h-16 w-2/3 animate-pulse rounded-lg bg-muted/40" />
        <div className="h-20 w-3/4 animate-pulse rounded-lg bg-muted/40" />
      </div>
    )
  }

  return (
    <>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex flex-1 flex-col gap-4 overflow-y-auto px-4 py-4"
        role="log"
        aria-live="polite"
        aria-label="Conversation"
      >
        {allMessages.length === 0 && !isStreaming && (
          <div className="mx-auto mt-16 max-w-md space-y-4 text-center">
            <SparklesIcon className="mx-auto h-10 w-10 text-primary/40" />
            <div className="space-y-1">
              <h3 className="text-base font-semibold">Ask your knowledge base anything</h3>
              <p className="text-sm text-muted-foreground">
                Questions are answered using indexed sources.
              </p>
            </div>
            <div className="grid gap-2 pt-2">
              {SUGGESTED_PROMPTS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => onSend?.(p)}
                  className="rounded-lg border border-border bg-card px-4 py-2.5 text-left text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        )}

        {allMessages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            sessionId={sessionId ?? ''}
            onCitationClick={(citation) => setPanel({ kind: 'citation', citation })}
            activitySnapshot={snapshots.get(msg.id)}
            onInspectStep={(step) => setPanel({ kind: 'step', step })}
            isLastAssistant={msg.id === lastAssistantId}
            isStreaming={isStreaming}
            continueDismissed={continueDismissed.has(msg.id)}
            onSearchAgain={() => onSend?.(KEEP_SEARCHING_PROMPT)}
            onLeaveBudget={() => setContinueDismissed((prev) => new Set(prev).add(msg.id))}
          />
        ))}

        {(() => {
          // The "in flight" assistant bubble appears either:
          //  - while SSE tokens are streaming (live text + caret), OR
          //  - in the silent gap between submit and first token (pulsing dots).
          // It always renders as a NEW row appended after the user bubble so
          // we never overwrite the user's optimistic message.
          const showThinkingBubble = isPending && !isStreaming
          if (!isStreaming && !showThinkingBubble) return null
          const hasToken = isStreaming && streamingToken.length > 0
          // Layer-1: once the agentic pipeline has narrated a plan/step, the
          // in-flight indicator becomes the live StatusLine. With no agentic
          // activity (flag off / classic pipeline) the log is empty and we keep
          // the existing PulsingDots — byte-identical to pre-004 behaviour.
          const hasAgenticActivity = activityLog.entries.length > 0
          return (
            <div className="flex items-start gap-3">
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-muted">
                <BotIcon className="h-4 w-4 text-muted-foreground" />
              </div>
              <div className="max-w-[75%] rounded-2xl rounded-tl-sm bg-muted px-4 py-2.5">
                {hasToken ? (
                  <div className="break-words text-sm">
                    <MarkdownLite content={streamingToken} />
                    <span
                      className="ml-0.5 inline-block h-3.5 w-0.5 bg-foreground align-middle"
                      aria-hidden="true"
                    />
                  </div>
                ) : hasAgenticActivity ? (
                  <StatusLine
                    activeStep={selectActiveStep(activityLog)}
                    budget={selectLatestBudget(activityLog)}
                    isStreaming={false}
                  />
                ) : (
                  <PulsingDots />
                )}
              </div>
            </div>
          )
        })()}

        <div ref={bottomRef} aria-hidden="true" />
      </div>

      <DetailPanel content={panel} onClose={() => setPanel(null)} />
    </>
  )
}

interface MessageBubbleProps {
  message: Message
  sessionId: string
  onCitationClick: (c: Citation) => void
  /** Per-turn activity snapshot for this assistant message (T-072) — drives the
   *  Layer-2 accordion. Undefined for user turns and for turns with no agentic
   *  activity (classic pipeline / flag off). */
  activitySnapshot?: ActivityState
  /** Open a step's payload in the slide-over (live snapshots only). */
  onInspectStep?: (step: StepActivityEntry) => void
  /** True if this is the most recent assistant turn (gates the budget-continue affordance). */
  isLastAssistant?: boolean
  /** True while a new turn is streaming (hides the affordance to prevent double-send). */
  isStreaming?: boolean
  /** True if the user already chose "Leave it here" on this turn. */
  continueDismissed?: boolean
  /** Start a fresh follow-up turn (budget "Search again"). */
  onSearchAgain?: () => void
  /** Locally dismiss the budget-continue affordance for this turn. */
  onLeaveBudget?: () => void
}

/**
 * Heuristic detection of synthesizer "I don't know" / fallback replies. We
 * dim and italicize these so a user can tell at a glance the system gave up
 * vs produced a real grounded answer. Match list is intentionally narrow and
 * length-bounded to avoid styling real answers that happen to begin with
 * similar phrasing in the middle of a long response.
 */
const FALLBACK_PATTERNS: readonly RegExp[] = [
  /^I don't (have|see) (enough information|anything|relevant)/i,
  /^(no relevant context|i couldn't find|i could not find)/i,
  /^sorry,?\s+i don't/i,
]

function isFallbackReply(content: string): boolean {
  if (content.length >= 240) return false
  return FALLBACK_PATTERNS.some((re) => re.test(content))
}

function MessageBubble({
  message,
  sessionId,
  onCitationClick,
  activitySnapshot,
  onInspectStep,
  isLastAssistant = false,
  isStreaming = false,
  continueDismissed = false,
  onSearchAgain,
  onLeaveBudget,
}: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isFallback = !isUser && isFallbackReply(message.content)

  const handleCopy = () => {
    navigator.clipboard
      .writeText(message.content)
      .then(() => toast.success('Copied'))
      .catch(() => toast.error('Failed to copy'))
  }

  return (
    <div
      className={cn('flex items-start gap-3', isUser && 'flex-row-reverse')}
      aria-label={isFallback ? 'Assistant unable to answer' : undefined}
    >
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
          isUser
            ? 'rounded-tr-sm bg-primary text-primary-foreground'
            : 'group rounded-tl-sm bg-muted',
          // Fallback assistant replies are visually softened so users can tell
          // at a glance the system did not produce a grounded answer.
          isFallback && 'bg-muted/40'
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap break-words text-sm">{message.content}</p>
        ) : (
          <div className={cn('break-words text-sm', isFallback && 'italic text-muted-foreground')}>
            {isFallback && (
              <InfoIcon
                className="mr-1.5 inline-block h-3.5 w-3.5 align-[-2px]"
                aria-hidden="true"
              />
            )}
            <MarkdownLite content={message.content} />
          </div>
        )}

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

        {/* Layer-2 finished-turn footer (accordion + budget + continue affordance).
            Shared with the admin sandbox via AgenticTurnFooter (004 review: Fix C). */}
        {!isUser && activitySnapshot && (
          <AgenticTurnFooter
            activity={activitySnapshot}
            isLastAssistant={isLastAssistant}
            isStreaming={isStreaming}
            continueDismissed={continueDismissed}
            onInspectStep={(step) => onInspectStep?.(step)}
            onSearchAgain={() => onSearchAgain?.()}
            onLeaveBudget={() => onLeaveBudget?.()}
          />
        )}

        {/* Bottom meta row: timestamp + (assistant only) feedback + copy.
            All on one line per UX spec — Option A from the inline-actions
            review.  Always visible on mobile (no hover dependency); icon-only
            ghost buttons keep visual weight low. */}
        <div
          className={cn(
            'mt-1 flex items-center gap-1',
            isUser ? 'text-primary-foreground/70' : 'text-muted-foreground'
          )}
        >
          <time
            className="text-[10px]"
            dateTime={message.created_at}
            aria-label={new Date(message.created_at).toLocaleString()}
          >
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: '2-digit',
              minute: '2-digit',
            })}
          </time>

          {!isUser && (
            <>
              <span aria-hidden className="select-none px-0.5 text-[10px] opacity-50">
                ·
              </span>
              <FeedbackButtons
                sessionId={sessionId}
                messageId={message.id}
                initialRating={message.feedback?.rating ?? null}
              />
              <button
                type="button"
                onClick={handleCopy}
                className="inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="Copy message"
                title="Copy message"
              >
                <CopyIcon className="h-3.5 w-3.5" aria-hidden />
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * Three soft dots that fade in/out on staggered intervals to signal "thinking"
 * while the model is processing but has not yet emitted its first SSE token.
 * Pure Tailwind animation — no JS timer, no extra renders.
 */
function PulsingDots() {
  return (
    <div
      className="flex items-center gap-1 py-0.5"
      role="status"
      aria-label="Assistant is thinking"
      data-testid="thinking-dots"
    >
      <span
        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/40 motion-reduce:animate-none"
        style={{ animationDelay: '0ms' }}
        aria-hidden="true"
      />
      <span
        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/40 motion-reduce:animate-none"
        style={{ animationDelay: '150ms' }}
        aria-hidden="true"
      />
      <span
        className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-foreground/40 motion-reduce:animate-none"
        style={{ animationDelay: '300ms' }}
        aria-hidden="true"
      />
    </div>
  )
}
