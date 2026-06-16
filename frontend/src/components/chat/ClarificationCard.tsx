'use client'

import { cn } from '@/lib/utils'
import { HelpCircleIcon, XIcon } from 'lucide-react'
import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import { OptionButtonGroup, type QuickReplyOption } from './OptionButtonGroup'

/**
 * One clarification choice (mirrors the backend ClarificationOption — see
 * contracts/sse-events.md: `{id, label, hint?, recommended?}`).
 *
 * SECURITY (Rule 2): options are drawn EXCLUSIVELY from the user's permitted
 * source set and re-clipped + labelled from the trusted server-side source name
 * by the backend (T-080). This component renders what it is given — it must
 * never be the place that decides which sources are offerable.
 */
export interface ClarificationOption {
  id: string
  label: string
  hint?: string | null
  recommended?: boolean | null
}

interface ClarificationCardProps {
  question: string
  /** When present, render quick-reply option buttons (the value sent is the id). */
  options?: ClarificationOption[]
  /** Whether to offer a free-text reply (defaults true per the wire contract). */
  allowFreeText?: boolean
  onReply: (answer: string) => void
  onDismiss: () => void
  disabled?: boolean
  /** Reset the free-text escape hatch across clarification rounds. */
  resetKey?: string | number
  /** Extra classes on the card root (e.g. the consumer's own margin). */
  className?: string
}

/**
 * Clarify-with-options card (T-081). Calm and collaborative — styled in the
 * feature's `bg-muted/40` language, NOT an alarming warning. When the backend
 * supplies permitted-source options it renders an OptionButtonGroup (reused
 * unchanged from T-075); otherwise it falls back to a free-text reply.
 */
export function ClarificationCard({
  question,
  options,
  allowFreeText = true,
  onReply,
  onDismiss,
  disabled = false,
  resetKey,
  className,
}: ClarificationCardProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const hasOptions = !!options && options.length > 0
  // Lock after the first reply so a fast double-click / double-Enter (option
  // OR free-text path) can't submit twice. Reset across clarification rounds.
  const [replied, setReplied] = useState(false)
  const locked = disabled || replied

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset is keyed solely on resetKey
  useEffect(() => {
    setReplied(false)
    if (textareaRef.current) textareaRef.current.value = ''
  }, [resetKey])

  // Single guarded + trimmed submit path for BOTH the option and free-text UIs.
  // INV (Rule 2 / T-080): the value sent here — an option id OR free text — is
  // UNTRUSTED. It re-enters as the next user turn, which the backend MUST
  // re-authorize against the user's permitted sources; this card performs NO
  // access enforcement and an option id is NOT a capability token.
  const submitReply = (raw: string) => {
    const value = raw.trim()
    if (!value || locked) return
    setReplied(true)
    onReply(value)
  }

  const handleFreeTextReply = () => {
    submitReply(textareaRef.current?.value ?? '')
    if (textareaRef.current) textareaRef.current.value = ''
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleFreeTextReply()
    }
  }

  const quickReplies: QuickReplyOption[] = (options ?? []).map((opt) => ({
    id: opt.id,
    label: opt.label,
    value: opt.id,
    recommended: opt.recommended ?? undefined,
    description: opt.hint ?? undefined,
  }))

  return (
    <div
      role="region"
      aria-label="Clarification needed"
      aria-live="polite"
      className={cn('mb-2 rounded-xl border border-border bg-muted/40 p-3', className)}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <p className="flex items-start gap-2 text-sm text-foreground">
          <HelpCircleIcon
            className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <span>{question}</span>
        </p>
        <button
          type="button"
          aria-label="Dismiss clarification"
          onClick={onDismiss}
          className={cn(
            'shrink-0 rounded p-0.5 text-muted-foreground transition-colors duration-150',
            'hover:bg-muted hover:text-foreground motion-reduce:transition-none',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
          )}
        >
          <XIcon className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>

      {hasOptions ? (
        <OptionButtonGroup
          options={quickReplies}
          onSelect={(value) => submitReply(value)}
          allowFreeText={allowFreeText}
          freeTextPlaceholder="Something else…"
          onFreeText={(text) => submitReply(text)}
          disabled={locked}
          resetKey={resetKey}
        />
      ) : (
        allowFreeText && (
          <div className="flex items-end gap-2">
            <textarea
              ref={textareaRef}
              aria-label="Clarification reply"
              className={cn(
                'flex-1 resize-none rounded-lg border border-border bg-background px-3 py-2 text-sm leading-5',
                'placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring',
                'disabled:cursor-not-allowed disabled:opacity-50'
              )}
              placeholder="Your answer…"
              rows={2}
              disabled={locked}
              onKeyDown={handleKeyDown}
            />
            <button
              type="button"
              aria-label="Send clarification reply"
              disabled={locked}
              onClick={handleFreeTextReply}
              className={cn(
                'h-9 shrink-0 rounded-lg bg-primary px-3 text-sm font-medium text-primary-foreground',
                'hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
              )}
            >
              Reply
            </button>
          </div>
        )
      )}
    </div>
  )
}
