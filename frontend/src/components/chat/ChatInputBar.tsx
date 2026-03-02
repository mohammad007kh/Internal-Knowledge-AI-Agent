'use client'

import { SendHorizontalIcon } from 'lucide-react'
import { type KeyboardEvent, useRef } from 'react'

const MAX_CHARS = 4000

interface ChatInputBarProps {
  onSend: (text: string) => void
  disabled?: boolean
  sessionId: string | null
}

export function ChatInputBar({ onSend, disabled = false, sessionId }: ChatInputBarProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const handleSend = () => {
    const value = textareaRef.current?.value.trim() ?? ''
    if (!value || disabled || !sessionId) return
    onSend(value)
    if (textareaRef.current) {
      textareaRef.current.value = ''
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleInput = () => {
    const el = textareaRef.current
    if (!el) return
    // Auto-grow textarea
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
    // Enforce max chars
    if (el.value.length > MAX_CHARS) {
      el.value = el.value.slice(0, MAX_CHARS)
    }
  }

  return (
    <form
      aria-label="Chat input"
      className="flex items-end gap-2 border-t border-border bg-background px-4 py-3"
      onSubmit={(e) => {
        e.preventDefault()
        handleSend()
      }}
    >
      <textarea
        ref={textareaRef}
        aria-label="Chat message input"
        className="flex-1 resize-none rounded-xl border border-input bg-muted px-3 py-2 text-sm leading-5 placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
        placeholder="Type a message… (Shift+Enter for new line)"
        rows={1}
        maxLength={MAX_CHARS}
        disabled={disabled || !sessionId}
        onKeyDown={handleKeyDown}
        onInput={handleInput}
      />
      <button
        type="submit"
        aria-label="Send message"
        disabled={disabled || !sessionId}
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <SendHorizontalIcon className="h-4 w-4" aria-hidden="true" />
      </button>
    </form>
  )
}
