'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { useEffect, useId, useState } from 'react'

/** One quick-reply option. Superset contract serving BOTH the honest-failure
 *  continue/stop prompt (T-075) AND the clarification source options (T-081). */
export interface QuickReplyOption {
  id: string
  label: string
  value: string
  /** Visually emphasised (filled) + announced as recommended. At most one. */
  recommended?: boolean
  /** Optional sub-label (e.g. a clarification source's scope hint). */
  description?: string
}

export interface OptionButtonGroupProps {
  /** Accessible name for the button group. */
  label?: string
  options: QuickReplyOption[]
  onSelect: (value: string, option: QuickReplyOption) => void
  /** Show a "Something else…" free-text escape hatch (clarification). */
  allowFreeText?: boolean
  freeTextPlaceholder?: string
  onFreeText?: (text: string) => void
  /** Disable the whole group (e.g. after a choice is made). */
  disabled?: boolean
  /** Change this (e.g. per clarification round / message id) to reset the
   *  free-text escape hatch — prevents a half-typed value leaking across
   *  consecutive uses at the same tree position. */
  resetKey?: string | number
  className?: string
}

/**
 * A row of quick-reply buttons (T-075). Real `<button>`s in a `role="group"`
 * with an accessible name → native Tab order + Enter/Space activation. Built
 * once here and REUSED by the ClarificationCard (T-081); the prop contract is a
 * superset of both consumers' needs.
 */
export function OptionButtonGroup({
  label,
  options,
  onSelect,
  allowFreeText = false,
  freeTextPlaceholder = 'Something else…',
  onFreeText,
  disabled = false,
  resetKey,
  className,
}: OptionButtonGroupProps) {
  const [freeTextOpen, setFreeTextOpen] = useState(false)
  const [freeText, setFreeText] = useState('')
  const inputId = useId()
  const labelId = useId()

  // Reset the free-text escape hatch when the consumer signals a new round, so
  // a half-typed value never bleeds across consecutive clarifications.
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset is keyed solely on resetKey
  useEffect(() => {
    setFreeTextOpen(false)
    setFreeText('')
  }, [resetKey])

  const submitFreeText = () => {
    if (disabled) return
    const trimmed = freeText.trim()
    if (!trimmed) return
    onFreeText?.(trimmed)
    setFreeText('')
  }

  return (
    <div
      role="group"
      aria-labelledby={label ? labelId : undefined}
      aria-label={label ? undefined : 'Quick replies'}
      className={cn('space-y-2', className)}
    >
      {label && (
        <p id={labelId} className="text-xs text-muted-foreground">
          {label}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        {options.map((opt) => (
          <button
            key={opt.id}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(opt.value, opt)}
            title={opt.description}
            className={cn(
              'inline-flex min-h-[44px] items-center rounded-full border px-3 py-1.5 text-xs',
              'transition-colors duration-150 motion-reduce:transition-none',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
              'disabled:cursor-not-allowed disabled:opacity-50',
              opt.recommended
                ? 'border-transparent bg-primary text-primary-foreground hover:bg-primary/90'
                : 'border-border bg-background text-foreground hover:bg-muted'
            )}
          >
            {opt.label}
            {opt.recommended && <span className="sr-only"> (recommended)</span>}
          </button>
        ))}

        {allowFreeText && !freeTextOpen && (
          <button
            type="button"
            disabled={disabled}
            aria-expanded={freeTextOpen}
            onClick={() => setFreeTextOpen(true)}
            className={cn(
              'inline-flex min-h-[44px] items-center rounded-full border border-dashed border-muted-foreground/40 px-3 py-1.5 text-xs text-muted-foreground',
              'transition-colors duration-150 hover:bg-muted hover:text-foreground motion-reduce:transition-none',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              'disabled:cursor-not-allowed disabled:opacity-50'
            )}
          >
            {freeTextPlaceholder}
          </button>
        )}
      </div>

      {allowFreeText && freeTextOpen && (
        <div className="flex items-center gap-2">
          <label htmlFor={inputId} className="sr-only">
            {freeTextPlaceholder}
          </label>
          <Input
            id={inputId}
            value={freeText}
            disabled={disabled}
            placeholder={freeTextPlaceholder}
            onChange={(e) => setFreeText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                submitFreeText()
              }
            }}
            className="h-9 text-sm"
          />
          <Button
            type="button"
            size="sm"
            disabled={disabled || !freeText.trim()}
            onClick={submitFreeText}
          >
            Send
          </Button>
        </div>
      )}
    </div>
  )
}
