'use client'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import { SendHorizontalIcon, SquareIcon } from 'lucide-react'
import { useCallback, useEffect, useRef } from 'react'
import { SourceChips } from './SourceChips'
import { SourceSelector } from './SourceSelector'
import { useSessionSources } from './useSessionSources'

interface ChatInputBarProps {
  onSend: (text: string) => void
  onStop?: () => void
  disabled?: boolean
  isStreaming?: boolean
  sessionId: string | null
  /**
   * True while the parent is in the middle of auto-creating a session in
   * response to a send. Used to disable the send button and the textarea
   * for the brief moment between submission and the new session being ready
   * so the user cannot fire two creates in a row.
   */
  isCreatingSession?: boolean
  /**
   * When true, the input is usable even with no session selected. The parent
   * is responsible for transparently creating a session before forwarding
   * the message to the stream (auto-create-on-send flow in `ChatLayout`).
   * Defaults to false to preserve existing call sites.
   */
  allowEmptySession?: boolean
}

const MAX_CHARS = 4000

export function ChatInputBar({
  onSend,
  onStop,
  disabled = false,
  isStreaming = false,
  sessionId,
  isCreatingSession = false,
  allowEmptySession = false,
}: ChatInputBarProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const { selectedIds, selectedSources, handleChange, handleRemove, isUpdating } =
    useSessionSources({ sessionId })

  const inputDisabled =
    disabled || isStreaming || isCreatingSession || (!sessionId && !allowEmptySession)
  const sendDisabled = disabled || isCreatingSession || (!sessionId && !allowEmptySession)

  const handleSend = useCallback(() => {
    const value = textareaRef.current?.value.trim()
    if (!value || disabled || isCreatingSession) return
    if (!sessionId && !allowEmptySession) return
    onSend(value)
    if (textareaRef.current) textareaRef.current.value = ''
  }, [disabled, onSend, sessionId, allowEmptySession, isCreatingSession])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend]
  )

  const handleStop = useCallback(() => {
    onStop?.()
  }, [onStop])

  useEffect(() => {
    if (!isStreaming) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onStop?.()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [isStreaming, onStop])

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
          if (isStreaming) {
            handleStop()
          } else {
            handleSend()
          }
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
          placeholder={
            isStreaming
              ? 'Generating… press Esc to stop'
              : isCreatingSession
                ? 'Creating chat…'
                : sessionId || allowEmptySession
                  ? 'Ask a question… (Enter to send)'
                  : 'Select a session first…'
          }
          className={cn('max-h-40 min-h-[2.75rem] flex-1 resize-none rounded-xl')}
          rows={1}
          maxLength={MAX_CHARS}
          disabled={inputDisabled}
          onKeyDown={handleKeyDown}
          aria-label="Chat message input"
        />
        {isStreaming ? (
          <Button
            type="button"
            size="icon"
            variant="destructive"
            onClick={handleStop}
            aria-label="Stop generation"
            className="shrink-0"
          >
            <SquareIcon className="h-4 w-4" />
          </Button>
        ) : (
          <Button
            type="submit"
            size="icon"
            disabled={sendDisabled}
            aria-label="Send message"
            className="shrink-0"
          >
            <SendHorizontalIcon className="h-4 w-4" />
          </Button>
        )}
      </form>
    </div>
  )
}
