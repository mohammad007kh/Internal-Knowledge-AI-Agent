'use client'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { SendHorizontalIcon } from 'lucide-react'
import { useCallback, useRef } from 'react'
import { SourceChips } from './SourceChips'
import { SourceSelector } from './SourceSelector'
import { useSessionSources } from './useSessionSources'

interface ChatInputBarProps {
  onSend: (text: string) => void
  disabled?: boolean
  sessionId: string | null
}

const MAX_CHARS = 4000

export function ChatInputBar({ onSend, disabled = false, sessionId }: ChatInputBarProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { selectedIds, selectedSources, handleChange, handleRemove, isUpdating } =
    useSessionSources({ sessionId })

  const handleSend = useCallback(() => {
    const value = textareaRef.current?.value.trim()
    if (!value || disabled || !sessionId) return
    onSend(value)
    if (textareaRef.current) textareaRef.current.value = ''
  }, [disabled, onSend, sessionId])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend]
  )

  return (
    <div className="border-t border-border bg-background">
      <SourceChips
        sources={selectedSources}
        onRemove={handleRemove}
        disabled={disabled || isUpdating}
      />
      <form
        className="flex items-end gap-2 px-4 py-3"
        onSubmit={(e) => {
          e.preventDefault()
          handleSend()
        }}
        aria-label="Chat input"
      >
        <SourceSelector
          selectedIds={selectedIds}
          onChange={handleChange}
          disabled={disabled || !sessionId || isUpdating}
        />
        <Textarea
          ref={textareaRef}
          placeholder={sessionId ? 'Ask a question… (Enter to send)' : 'Select a session first…'}
          className={cn('max-h-40 min-h-[2.75rem] flex-1 resize-none rounded-xl')}
          rows={1}
          maxLength={MAX_CHARS}
          disabled={disabled || !sessionId}
          onKeyDown={handleKeyDown}
          aria-label="Chat message input"
        />
        <Button
          type="submit"
          size="icon"
          disabled={disabled || !sessionId}
          aria-label="Send message"
          className="shrink-0"
        >
          <SendHorizontalIcon className="h-4 w-4" />
        </Button>
      </form>
    </div>
  )
}
