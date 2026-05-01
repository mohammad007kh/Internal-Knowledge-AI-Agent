'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'
import { KeyRoundIcon } from 'lucide-react'

/**
 * Shared API-key form field used by AI Model and Embedder forms.
 *
 * Two modes:
 *  - **Create**: always reveals an empty `type=password` input. Required.
 *  - **Edit**: shows a read-only mask (`••••• Last 4: 1234`) with a "Replace
 *    API key" toggle. When toggled on, exposes an empty `type=password`
 *    input — submitting that path overwrites the stored key. Toggle off =
 *    preserve the existing key (omit `api_key` from the PATCH).
 *
 * Security invariants enforced here:
 *  - Masked field is read-only with `disabled` copy semantics.
 *  - Real input is `type=password` with `autoComplete="new-password"`.
 *  - The plaintext is held only in component state, never echoed to the DOM
 *    in a copyable way.
 */

interface ApiKeyFieldProps {
  id: string
  /** ``true`` when the form is editing an existing record. */
  isEdit: boolean
  /** Last 4 chars of the stored key (only meaningful when ``isEdit``). */
  last4: string | null
  /** Whether the user has toggled "Replace API key" on. */
  replaceMode: boolean
  /** Plaintext of the new key (controlled). Empty string = no value yet. */
  value: string
  /** Form-level error text (optional). */
  error?: string | null
  onReplaceModeChange: (replace: boolean) => void
  onValueChange: (next: string) => void
}

const NEVER_DISPLAY_KEY_PLACEHOLDER = '••••••••••••'

export function ApiKeyField({
  id,
  isEdit,
  last4,
  replaceMode,
  value,
  error,
  onReplaceModeChange,
  onValueChange,
}: ApiKeyFieldProps) {
  const showInput = !isEdit || replaceMode
  const inputRequired = !isEdit || replaceMode

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={id}>
          API key
          {inputRequired ? <span className="ml-1 text-destructive">*</span> : null}
        </Label>
        {isEdit ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1.5 px-2 text-xs"
            onClick={() => onReplaceModeChange(!replaceMode)}
          >
            <KeyRoundIcon className="h-3.5 w-3.5" aria-hidden />
            {replaceMode ? 'Keep existing key' : 'Replace API key'}
          </Button>
        ) : null}
      </div>

      {isEdit && !replaceMode ? (
        <div
          className={cn(
            'flex h-10 w-full items-center rounded-md border border-input bg-muted/30 px-3 text-sm',
            'font-mono tracking-wider text-muted-foreground'
          )}
          aria-label="Stored API key (masked)"
          // Block clipboard copy on the masked surface — defense in depth.
          onCopy={(event) => event.preventDefault()}
        >
          <span aria-hidden>{NEVER_DISPLAY_KEY_PLACEHOLDER}</span>
          {last4 ? (
            <span className="ml-3 text-xs uppercase tracking-wider text-muted-foreground/80">
              Last 4: <span className="font-mono normal-case">{last4}</span>
            </span>
          ) : (
            <span className="ml-3 text-xs uppercase tracking-wider text-muted-foreground/80">
              Not set
            </span>
          )}
        </div>
      ) : null}

      {showInput ? (
        <Input
          id={id}
          type="password"
          autoComplete="new-password"
          spellCheck={false}
          required={inputRequired}
          placeholder={isEdit ? 'Paste new API key' : 'sk-...'}
          value={value}
          onChange={(event) => onValueChange(event.target.value)}
          aria-invalid={Boolean(error) || undefined}
          aria-describedby={error ? `${id}-error` : undefined}
        />
      ) : null}

      {error ? (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          {isEdit
            ? replaceMode
              ? 'A new key will overwrite the stored value.'
              : 'Stored key is preserved when not replaced.'
            : 'Stored encrypted at rest. Never re-displayed after save.'}
        </p>
      )}
    </div>
  )
}
