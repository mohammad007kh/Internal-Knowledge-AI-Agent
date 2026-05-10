'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { usersKeys } from '@/features/users/hooks/useUsersQueries'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckIcon, PencilIcon, XIcon } from 'lucide-react'
import { type ReactNode, useEffect, useId, useRef, useState } from 'react'
import { toast } from 'sonner'

/**
 * UserProfileSection
 * ------------------------------------------------------------
 * Renders the static "Profile" block in the View User Sheet.
 * Each editable field has its own [Edit] chip that toggles a
 * tiny inline editor and PATCHes /api/v1/users/{id} independently.
 * Per the spec: per-field, auto-save, no big "Save" button.
 */

interface UserProfileSectionProps {
  userId: string
  fullName: string | null
  email: string
  createdAt: string
}

interface InlineFieldProps {
  label: string
  value: string | null
  /** What to render when the field is empty (e.g. "Not set"). */
  placeholderDisplay?: string
  /** Render-only (no Edit chip) when true. */
  readOnly?: boolean
  inputType?: 'text' | 'email'
  /** Validates raw input — returns an error message or null. */
  validate?: (raw: string) => string | null
  /** PATCH body builder. */
  buildPatch: (raw: string) => Record<string, unknown>
  userId: string
  /** Optional formatter when not editing (e.g. dates). */
  display?: (value: string | null) => ReactNode
  successMessage: string
}

function InlineField({
  label,
  value,
  placeholderDisplay = '—',
  readOnly = false,
  inputType = 'text',
  validate,
  buildPatch,
  userId,
  display,
  successMessage,
}: InlineFieldProps) {
  const queryClient = useQueryClient()
  const fieldId = useId()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<string>(value ?? '')
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (editing) {
      setDraft(value ?? '')
      setError(null)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [editing, value])

  const mutation = useMutation({
    mutationFn: (raw: string) => apiClient.patch(`/api/v1/users/${userId}`, buildPatch(raw)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
      toast.success(successMessage)
      setEditing(false)
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : 'Update failed'
      toast.error(message)
    },
  })

  const submit = () => {
    if (validate) {
      const v = validate(draft)
      if (v) {
        setError(v)
        return
      }
    }
    if ((value ?? '') === draft.trim()) {
      // No-op: just close.
      setEditing(false)
      return
    }
    mutation.mutate(draft.trim())
  }

  return (
    <div className="grid grid-cols-[120px_1fr_auto] items-center gap-2 py-1.5 sm:grid-cols-[140px_1fr_auto]">
      <Label htmlFor={fieldId} className="text-xs text-muted-foreground">
        {label}
      </Label>
      {editing ? (
        <>
          <div className="min-w-0">
            <Input
              id={fieldId}
              ref={inputRef}
              type={inputType}
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value)
                if (error) setError(null)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  submit()
                } else if (e.key === 'Escape') {
                  e.preventDefault()
                  setEditing(false)
                }
              }}
              aria-invalid={!!error}
              aria-describedby={error ? `${fieldId}-error` : undefined}
              className="h-8 text-sm"
            />
            {error && (
              <p id={`${fieldId}-error`} className="mt-1 text-xs text-destructive">
                {error}
              </p>
            )}
          </div>
          <div className="flex gap-1">
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-8 w-8"
              onClick={submit}
              disabled={mutation.isPending}
              aria-label={`Save ${label.toLowerCase()}`}
            >
              <CheckIcon className="h-3.5 w-3.5" aria-hidden />
            </Button>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-8 w-8"
              onClick={() => setEditing(false)}
              disabled={mutation.isPending}
              aria-label={`Cancel ${label.toLowerCase()} edit`}
            >
              <XIcon className="h-3.5 w-3.5" aria-hidden />
            </Button>
          </div>
        </>
      ) : (
        <>
          <span
            className={cn(
              'min-w-0 truncate text-sm',
              !value && 'italic text-muted-foreground'
            )}
            title={value ?? ''}
          >
            {display ? display(value) : (value ?? placeholderDisplay)}
          </span>
          {readOnly ? (
            <span aria-hidden />
          ) : (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 gap-1 px-2 text-xs"
              onClick={() => setEditing(true)}
              aria-label={`Edit ${label.toLowerCase()}`}
            >
              <PencilIcon className="h-3 w-3" aria-hidden />
              Edit
            </Button>
          )}
        </>
      )}
    </div>
  )
}

export function UserProfileSection({
  userId,
  fullName,
  email,
  createdAt,
}: UserProfileSectionProps) {
  return (
    <section aria-label="Profile" className="space-y-1">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Profile
      </h3>
      <div className="rounded-md border bg-card/40 p-2">
        <InlineField
          label="Full name"
          value={fullName}
          userId={userId}
          buildPatch={(raw) => ({ full_name: raw.length > 0 ? raw : null })}
          successMessage="Name updated."
        />
        <InlineField
          label="Email"
          value={email}
          userId={userId}
          inputType="email"
          validate={(raw) => {
            if (!raw.trim()) return 'Email is required.'
            // Lightweight client-side check; the backend is authoritative.
            if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(raw.trim())) {
              return 'Enter a valid email address.'
            }
            return null
          }}
          buildPatch={(raw) => ({ email: raw })}
          successMessage="Email updated."
        />
        <InlineField
          label="Created"
          value={createdAt}
          readOnly
          buildPatch={() => ({})}
          userId={userId}
          successMessage=""
          display={(v) =>
            v
              ? new Date(v).toLocaleDateString(undefined, {
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                })
              : '—'
          }
        />
      </div>
    </section>
  )
}
