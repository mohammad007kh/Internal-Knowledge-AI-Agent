'use client'

import { cn } from '@/lib/utils'

/**
 * SegmentedControl — a compact pill-style single-select toggle.
 *
 * Originally lived inside `app/(admin)/admin/llm-settings/_components/StagesToolbar.tsx`;
 * extracted here so the analytics dashboard and the LLM-settings toolbar share
 * one implementation. Strictly presentational — owns no state.
 *
 * Usage:
 *   <SegmentedControl
 *     label="Range"
 *     options={[{ value: '7d', label: '7d' }, { value: '30d', label: '30d' }]}
 *     value={range}
 *     onChange={setRange}
 *   />
 */

export interface SegmentedControlOption<T extends string> {
  value: T
  label: string
}

export interface SegmentedControlProps<T extends string> {
  /** Accessible label for the radio-group; also rendered as a `Label:` prefix unless `hideLabel`. */
  label: string
  options: ReadonlyArray<SegmentedControlOption<T>>
  value: T
  onChange: (value: T) => void
  hideLabel?: boolean
  className?: string
}

export function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
  hideLabel,
  className,
}: SegmentedControlProps<T>) {
  return (
    <div className={cn('inline-flex items-center gap-2', className)}>
      {hideLabel ? null : (
        <span className="text-xs text-muted-foreground" aria-hidden>
          {label}:
        </span>
      )}
      <div
        role="group"
        aria-label={label}
        className="inline-flex items-center rounded-full border bg-background p-0.5"
      >
        {options.map((opt) => {
          const isActive = opt.value === value
          return (
            <button
              key={opt.value}
              type="button"
              onClick={() => onChange(opt.value)}
              aria-pressed={isActive}
              className={cn(
                'inline-flex h-6 items-center rounded-full px-2.5 text-xs font-medium transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {opt.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}
