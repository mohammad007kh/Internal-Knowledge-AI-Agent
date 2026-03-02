'use client'

import { HelpCircleIcon, XIcon } from 'lucide-react'
import { type KeyboardEvent, useRef } from 'react'

interface ClarificationCardProps {
  question: string
  onDismiss: () => void
  onReply: (answer: string) => void
  disabled?: boolean
}

export function ClarificationCard({
  question,
  onDismiss,
  onReply,
  disabled = false,
}: ClarificationCardProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleReply = () => {
    const value = textareaRef.current?.value.trim() ?? ''
    if (!value || disabled) return
    onReply(value)
    if (textareaRef.current) {
      textareaRef.current.value = ''
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleReply()
    }
  }

  return (
    <div
      role="region"
      aria-label="Clarification needed"
      className="mx-4 mb-2 rounded-xl border border-yellow-200 bg-yellow-50 p-3 dark:border-yellow-800 dark:bg-yellow-950"
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <div className="flex items-start gap-2">
          <HelpCircleIcon
            className="mt-0.5 h-4 w-4 shrink-0 text-yellow-600 dark:text-yellow-400"
            aria-hidden="true"
          />
          <p className="text-sm text-yellow-800 dark:text-yellow-200">{question}</p>
        </div>
        <button
          type="button"
          aria-label="Dismiss clarification"
          onClick={onDismiss}
          className="shrink-0 rounded p-0.5 text-yellow-600 hover:bg-yellow-100 dark:text-yellow-400 dark:hover:bg-yellow-900"
        >
          <XIcon className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          aria-label="Clarification reply"
          className="flex-1 resize-none rounded-lg border border-yellow-300 bg-white px-3 py-2 text-sm leading-5 placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-yellow-400 disabled:cursor-not-allowed disabled:opacity-50 dark:border-yellow-700 dark:bg-yellow-900"
          placeholder="Your answer…"
          rows={2}
          disabled={disabled}
          onKeyDown={handleKeyDown}
        />
        <button
          type="button"
          aria-label="Send clarification reply"
          disabled={disabled}
          onClick={handleReply}
          className="shrink-0 rounded-lg bg-yellow-500 px-3 py-2 text-sm font-medium text-white hover:bg-yellow-600 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-yellow-600 dark:hover:bg-yellow-700"
        >
          Reply
        </button>
      </div>
    </div>
  )
}
