'use client'

/**
 * EditCredentialsDialog (U8 + FX4)
 *
 * Settings-tab affordance to rotate a database source's connection
 * credentials. Mounted from the Connection card; opened when the admin
 * clicks "Edit credentials".
 *
 * UX contract — every part of which is enforced by the backend:
 *
 *   1. The admin types ONLY the fields they want to change. Fields left
 *      blank fall through to the existing stored values server-side.
 *   2. A "Confirm your password" field at the bottom re-authenticates the
 *      admin (FX4). Wrong password → 401 → inline error, dialog stays open.
 *   3. On Save the backend runs Test Connection BEFORE persisting. A
 *      connector failure → 422 → we surface the error inline and the
 *      dialog stays open. On success: connection_status resets to
 *      `unknown`, source becomes "temporarily unavailable" until the next
 *      Test Connection succeeds, and an audit row is written.
 *
 * SECURITY
 *   - Both password fields are type=password and never echoed.
 *   - The submitted body is never console.log'd. The shared apiClient
 *     does not log request bodies on errors either.
 */

import { Button } from '@/components/ui/button'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { sourcesKeys } from '@/features/sources/hooks/useSources'
import {
  type SourceDetail,
  type UpdateSourceCredentialsRequest,
  updateSourceCredentialsApi,
} from '@/lib/api/sources'
import { getErrorMessage } from '@/lib/errors'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangleIcon, Loader2Icon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

// ---------------------------------------------------------------------------
// Local form state — distinct from the wire shape because empty strings
// signal "leave unchanged" client-side; we drop them before posting so the
// backend's omit-merging path kicks in.
// ---------------------------------------------------------------------------

interface CredentialsFormState {
  db_type: 'postgresql' | 'mysql' | 'mssql' | 'mongodb' | ''
  host: string
  port: string
  database: string
  username: string
  password: string
  confirm_password: string
}

const EMPTY_FORM: CredentialsFormState = {
  db_type: '',
  host: '',
  port: '',
  database: '',
  username: '',
  password: '',
  confirm_password: '',
}

interface EditCredentialsDialogProps {
  source: SourceDetail
  open: boolean
  onOpenChange: (open: boolean) => void
}

/**
 * Dialog component. Stateless w.r.t. parent — the parent owns the open
 * boolean so other actions (e.g. clicking outside) can close it. On
 * successful save we close ourselves and invalidate the source detail
 * query so the page header pill flips to "Unknown".
 */
export function EditCredentialsDialog({
  source,
  open,
  onOpenChange,
}: EditCredentialsDialogProps) {
  const [form, setForm] = useState<CredentialsFormState>(EMPTY_FORM)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: (body: UpdateSourceCredentialsRequest) =>
      updateSourceCredentialsApi(source.id, body),
    onSuccess: () => {
      toast.success(
        'Credentials updated. Run Test Connection to confirm reachability.'
      )
      // Force the detail page to refetch so connection_status flips to
      // "unknown" in the pill and the "last tested" line clears.
      queryClient.invalidateQueries({
        queryKey: sourcesKeys.detail(source.id),
      })
      queryClient.invalidateQueries({ queryKey: sourcesKeys.list() })
      // Reset and close.
      setForm(EMPTY_FORM)
      setSubmitError(null)
      onOpenChange(false)
    },
    onError: (err) => {
      // Surface inline; don't close the dialog. The backend wraps both
      // 401 (wrong confirm_password) and 422 (connector test failed) in
      // the same RFC-7807 envelope, so the error message tells the
      // admin which side failed.
      //
      // We prefer the raw message when available because the global
      // `getErrorMessage` fallback collapses every non-status error into
      // the generic "Something went wrong" string — which would hide the
      // exact "Confirm-password does not match." / "Connection test
      // failed." copy the backend painstakingly emits.
      const message =
        err instanceof Error && err.message
          ? err.message
          : getErrorMessage(err)
      setSubmitError(message)
    },
  })

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitError(null)

    if (form.confirm_password.trim().length === 0) {
      setSubmitError('Confirm your password to apply changes.')
      return
    }

    // Build a minimal payload — strip empty strings so the backend keeps the
    // existing stored value for fields the admin didn't touch.
    const payload: UpdateSourceCredentialsRequest = {
      confirm_password: form.confirm_password,
    }
    if (form.db_type !== '') payload.db_type = form.db_type
    if (form.host.trim()) payload.host = form.host.trim()
    if (form.port.trim()) {
      const portNumber = Number.parseInt(form.port, 10)
      if (Number.isNaN(portNumber) || portNumber < 1 || portNumber > 65535) {
        setSubmitError('Port must be a number between 1 and 65535.')
        return
      }
      payload.port = portNumber
    }
    if (form.database.trim()) payload.database = form.database.trim()
    if (form.username.trim()) payload.username = form.username.trim()
    if (form.password.length > 0) payload.password = form.password

    // At least one credential field must be supplied.
    const credentialKeys = [
      'db_type',
      'host',
      'port',
      'database',
      'username',
      'password',
    ] as const
    const hasAnyChange = credentialKeys.some((k) => k in payload)
    if (!hasAnyChange) {
      setSubmitError('Provide at least one field to change.')
      return
    }

    mutation.mutate(payload)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-[520px]"
        data-testid="edit-credentials-dialog"
      >
        <DialogHeader>
          <DialogTitle>Edit connection credentials</DialogTitle>
          <DialogDescription>
            Rotate the database connection for &ldquo;{source.name}&rdquo;.
            Leave fields blank to keep the current value.
          </DialogDescription>
        </DialogHeader>

        {/* Stern warning — the backend resets connection_status and the
            source becomes temporarily unavailable until the next probe. */}
        <div
          role="alert"
          className="flex gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-900 dark:text-amber-200"
          data-testid="edit-credentials-warning"
        >
          <AlertTriangleIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <div className="space-y-1">
            <p className="font-medium">Saving will:</p>
            <ul className="list-disc space-y-0.5 pl-4">
              <li>Reset the connection status pill to &ldquo;Unknown&rdquo;.</li>
              <li>
                Make this source temporarily unavailable to chat users until
                a Test Connection succeeds.
              </li>
              <li>Write an audit log entry naming you as the editor.</li>
              <li>
                Run a Test Connection FIRST — if it fails, nothing is saved.
              </li>
            </ul>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-4"
          aria-label="Edit credentials"
        >
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2 space-y-1.5">
              <Label htmlFor="db_type">Type</Label>
              <Select
                value={form.db_type === '' ? undefined : form.db_type}
                onValueChange={(v) =>
                  setForm((f) => ({
                    ...f,
                    db_type: v as CredentialsFormState['db_type'],
                  }))
                }
              >
                <SelectTrigger id="db_type" data-testid="cred-db-type">
                  <SelectValue placeholder="Keep current" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="postgresql">PostgreSQL</SelectItem>
                  <SelectItem value="mysql">MySQL</SelectItem>
                  <SelectItem value="mssql">SQL Server</SelectItem>
                  <SelectItem value="mongodb">MongoDB</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="col-span-2 space-y-1.5 sm:col-span-1">
              <Label htmlFor="host">Host</Label>
              <Input
                id="host"
                autoComplete="off"
                placeholder="db.example.com"
                value={form.host}
                onChange={(e) =>
                  setForm((f) => ({ ...f, host: e.target.value }))
                }
                data-testid="cred-host"
              />
            </div>

            <div className="col-span-2 space-y-1.5 sm:col-span-1">
              <Label htmlFor="port">Port</Label>
              <Input
                id="port"
                inputMode="numeric"
                pattern="[0-9]*"
                autoComplete="off"
                placeholder="5432"
                value={form.port}
                onChange={(e) =>
                  setForm((f) => ({ ...f, port: e.target.value }))
                }
                data-testid="cred-port"
              />
            </div>

            <div className="col-span-2 space-y-1.5">
              <Label htmlFor="database">Database</Label>
              <Input
                id="database"
                autoComplete="off"
                value={form.database}
                onChange={(e) =>
                  setForm((f) => ({ ...f, database: e.target.value }))
                }
                data-testid="cred-database"
              />
            </div>

            <div className="col-span-2 space-y-1.5 sm:col-span-1">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                autoComplete="off"
                value={form.username}
                onChange={(e) =>
                  setForm((f) => ({ ...f, username: e.target.value }))
                }
                data-testid="cred-username"
              />
            </div>

            <div className="col-span-2 space-y-1.5 sm:col-span-1">
              <Label htmlFor="password">New password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                placeholder="Leave blank to keep current"
                value={form.password}
                onChange={(e) =>
                  setForm((f) => ({ ...f, password: e.target.value }))
                }
                data-testid="cred-password"
              />
            </div>
          </div>

          <hr className="my-2 border-t" />

          <div className="space-y-1.5">
            <Label htmlFor="confirm_password" className="font-semibold">
              Confirm your password
            </Label>
            <Input
              id="confirm_password"
              type="password"
              autoComplete="current-password"
              placeholder="Your account password"
              value={form.confirm_password}
              onChange={(e) =>
                setForm((f) => ({ ...f, confirm_password: e.target.value }))
              }
              aria-required="true"
              data-testid="cred-confirm-password"
            />
            <p className="text-xs text-muted-foreground">
              Required. Re-authenticates you before this credential change is
              applied.
            </p>
          </div>

          {submitError !== null && (
            <p
              className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive"
              role="alert"
              data-testid="edit-credentials-error"
            >
              {submitError}
            </p>
          )}

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onOpenChange(false)}
              disabled={mutation.isPending}
              data-testid="edit-credentials-cancel"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={mutation.isPending}
              data-testid="edit-credentials-save"
            >
              {mutation.isPending ? (
                <>
                  <Loader2Icon
                    className="mr-1.5 h-4 w-4 animate-spin"
                    aria-hidden
                  />
                  Testing &amp; saving…
                </>
              ) : (
                <>Test &amp; save</>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
