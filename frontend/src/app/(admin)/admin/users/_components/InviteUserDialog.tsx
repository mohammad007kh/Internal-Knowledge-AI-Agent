'use client'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { usersKeys } from '@/features/users/hooks/useUsersQueries'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronRightIcon, SendIcon, ShieldCheckIcon, UserIcon } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useEffect, useId, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

/**
 * InviteUserDialog
 * ------------------------------------------------------------
 * Centered Dialog (max-w-md). Reads `?invite=1` from the URL —
 * any page that mounts this component gets the modal "for free"
 * and the URL is the source of truth (deeplinkable, refresh-safe,
 * back-button closes).
 *
 * Form fields:
 *   - email           (autofocused on open)
 *   - role            (Member | Admin) as a 2-card radio
 *   - welcome message (optional, collapsible)
 *
 * "Send another?" sticky checkbox in the footer:
 *   - checked: on submit -> reset, refocus email, toast ok, stay open
 *   - unchecked: close on submit
 */

const inviteSchema = z.object({
  email: z.string().email('Enter a valid email address'),
  role: z.enum(['user', 'admin']),
  message: z.string().max(500).optional(),
})
type InviteFormValues = z.infer<typeof inviteSchema>

interface RoleOption {
  value: 'user' | 'admin'
  label: string
  description: string
  icon: typeof UserIcon
}

const ROLE_OPTIONS: ReadonlyArray<RoleOption> = [
  {
    value: 'user',
    label: 'Member',
    description: 'Ask questions, read sources',
    icon: UserIcon,
  },
  {
    value: 'admin',
    label: 'Admin',
    description: 'Manage sources and other users',
    icon: ShieldCheckIcon,
  },
]

interface InvitePayload {
  email: string
  role: 'user' | 'admin'
  message?: string
}

async function inviteUserApi(payload: InvitePayload): Promise<void> {
  await apiClient.post('/api/v1/users/invitations', payload)
}

export function InviteUserDialog() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const queryClient = useQueryClient()

  const isOpen = searchParams.get('invite') === '1'

  const emailFieldId = useId()
  const messageFieldId = useId()
  const sendAnotherId = useId()
  const roleGroupLabelId = useId()

  const emailRef = useRef<HTMLInputElement | null>(null)
  const [sendAnother, setSendAnother] = useState(false)
  const [showMessage, setShowMessage] = useState(false)

  const form = useForm<InviteFormValues>({
    resolver: zodResolver(inviteSchema),
    defaultValues: { email: '', role: 'user', message: '' },
  })
  const {
    register,
    handleSubmit,
    setValue,
    watch,
    reset,
    formState: { errors, isSubmitting },
  } = form

  const role = watch('role')
  const { ref: emailRegisterRef, ...emailRegisterRest } = register('email')

  const closeDialog = () => {
    // Preserve the page; just drop the ?invite=1 param.
    router.replace('/admin/users')
  }

  // Reset transient UI state every time the modal closes so re-opening
  // gives a clean slate.
  useEffect(() => {
    if (!isOpen) {
      reset({ email: '', role: 'user', message: '' })
      setSendAnother(false)
      setShowMessage(false)
    }
  }, [isOpen, reset])

  const inviteMutation = useMutation({
    mutationFn: inviteUserApi,
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
      queryClient.invalidateQueries({ queryKey: usersKeys.invitations() })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })

      if (sendAnother) {
        toast.success(`Invitation sent to ${variables.email}`)
        reset({ email: '', role: 'user', message: '' })
        setShowMessage(false)
        // Refocus the email field on the next tick so the user can
        // immediately type the next address.
        requestAnimationFrame(() => emailRef.current?.focus())
      } else {
        toast.success(`Invitation sent to ${variables.email}`)
        closeDialog()
      }
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : 'Failed to send invitation'
      toast.error(message)
    },
  })

  const onSubmit = handleSubmit((values) => {
    const payload: InvitePayload = {
      email: values.email,
      role: values.role,
      ...(values.message && values.message.trim().length > 0
        ? { message: values.message.trim() }
        : {}),
    }
    inviteMutation.mutate(payload)
  })

  return (
    <Dialog open={isOpen} onOpenChange={(o) => !o && closeDialog()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Invite a teammate</DialogTitle>
          <DialogDescription>
            They&apos;ll receive an email with a one-time signup link.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} noValidate className="space-y-5">
          {/* Email */}
          <div className="space-y-1.5">
            <Label htmlFor={emailFieldId}>Email address</Label>
            <Input
              id={emailFieldId}
              type="email"
              placeholder="name@company.com"
              autoComplete="email"
              autoFocus
              aria-invalid={!!errors.email}
              aria-describedby={errors.email ? `${emailFieldId}-error` : undefined}
              {...emailRegisterRest}
              ref={(el) => {
                emailRegisterRef(el)
                emailRef.current = el
              }}
            />
            {errors.email && (
              <p id={`${emailFieldId}-error`} className="text-sm text-destructive">
                {errors.email.message}
              </p>
            )}
          </div>

          {/* Role: 2-card radio */}
          <div className="space-y-1.5">
            <span id={roleGroupLabelId} className="block text-sm font-medium">
              Role
            </span>
            <div
              role="radiogroup"
              aria-labelledby={roleGroupLabelId}
              className="grid gap-2"
            >
              {ROLE_OPTIONS.map((opt) => {
                const checked = role === opt.value
                const Icon = opt.icon
                return (
                  <button
                    key={opt.value}
                    type="button"
                    role="radio"
                    aria-checked={checked}
                    onClick={() =>
                      setValue('role', opt.value, {
                        shouldValidate: true,
                        shouldDirty: true,
                      })
                    }
                    onKeyDown={(e) => {
                      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                        e.preventDefault()
                        const next =
                          ROLE_OPTIONS[
                            (ROLE_OPTIONS.findIndex((o) => o.value === role) +
                              (e.key === 'ArrowDown' ? 1 : -1) +
                              ROLE_OPTIONS.length) %
                              ROLE_OPTIONS.length
                          ]
                        setValue('role', next.value, {
                          shouldValidate: true,
                          shouldDirty: true,
                        })
                      }
                    }}
                    className={cn(
                      'flex w-full items-start gap-3 rounded-md border p-3 text-left transition-colors',
                      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                      checked
                        ? 'border-primary bg-primary/5 ring-1 ring-primary/40'
                        : 'border-input hover:bg-accent/40'
                    )}
                  >
                    <span
                      className={cn(
                        'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
                        checked ? 'border-primary' : 'border-muted-foreground/40'
                      )}
                      aria-hidden
                    >
                      {checked ? <span className="h-2 w-2 rounded-full bg-primary" /> : null}
                    </span>
                    <span className="flex-1">
                      <span className="flex items-center gap-1.5 text-sm font-medium">
                        <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                        {opt.label}
                      </span>
                      <span className="block text-xs text-muted-foreground">
                        {opt.description}
                      </span>
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Optional welcome message (collapsible) */}
          <div>
            <button
              type="button"
              onClick={() => setShowMessage((v) => !v)}
              aria-expanded={showMessage}
              aria-controls={messageFieldId}
              className="inline-flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              <ChevronRightIcon
                className={cn(
                  'h-3.5 w-3.5 transition-transform',
                  showMessage && 'rotate-90'
                )}
                aria-hidden
              />
              Add a personal note (optional)
            </button>
            {showMessage && (
              <div className="mt-2 space-y-1.5">
                <Label htmlFor={messageFieldId} className="sr-only">
                  Personal note
                </Label>
                <Textarea
                  id={messageFieldId}
                  rows={3}
                  placeholder="Hey, joining our knowledge base — looking forward to having you."
                  {...register('message')}
                />
              </div>
            )}
          </div>

          <p className="text-xs text-muted-foreground">Invite expires in 7 days.</p>

          <DialogFooter className="flex flex-col-reverse gap-3 border-t pt-4 sm:flex-row sm:items-center sm:justify-between sm:space-x-0">
            <label
              htmlFor={sendAnotherId}
              className="flex items-center gap-2 text-sm text-muted-foreground"
            >
              <Checkbox
                id={sendAnotherId}
                checked={sendAnother}
                onCheckedChange={setSendAnother}
              />
              Send another after this one
            </label>
            <div className="flex gap-2">
              <Button type="button" variant="outline" onClick={closeDialog}>
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmitting || inviteMutation.isPending}>
                {inviteMutation.isPending ? 'Sending…' : 'Send'}
                <SendIcon className="ml-1.5 h-3.5 w-3.5" aria-hidden />
              </Button>
            </div>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
