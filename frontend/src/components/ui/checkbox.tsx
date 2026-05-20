'use client'

import { CheckIcon } from 'lucide-react'
import * as React from 'react'

import { cn } from '@/lib/utils'

export interface CheckboxProps
  extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'onChange'> {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}

/**
 * Accessible checkbox. Dependency-free (no Radix) since
 * `@radix-ui/react-checkbox` is not installed in this project — modeled on
 * the same pattern as `Switch` so the visual + a11y conventions match the
 * rest of the shadcn-derived UI primitives.
 *
 * Usage:
 *   <Checkbox checked={agree} onCheckedChange={setAgree} id="terms" />
 */
export const Checkbox = React.forwardRef<HTMLButtonElement, CheckboxProps>(
  ({ checked, onCheckedChange, disabled, className, id, ...rest }, ref) => {
    return (
      <button
        ref={ref}
        id={id}
        type="button"
        role="checkbox"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onCheckedChange(!checked)}
        // WAI-ARIA 1.1: a checkbox MUST toggle on Space. Most modern
        // browsers synthesise a click for Space on <button>, but some AT /
        // browser combinations forward keypress instead — handle it
        // explicitly so the contract holds regardless.
        onKeyDown={(e) => {
          if (e.key === ' ' || e.key === 'Spacebar') {
            e.preventDefault()
            if (!disabled) onCheckedChange(!checked)
          }
        }}
        className={cn(
          'peer inline-flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded-sm border border-primary text-primary-foreground transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
          'disabled:cursor-not-allowed disabled:opacity-50',
          checked ? 'bg-primary' : 'bg-background',
          className
        )}
        {...rest}
      >
        {checked ? <CheckIcon className="h-3 w-3" aria-hidden /> : null}
      </button>
    )
  }
)
Checkbox.displayName = 'Checkbox'
