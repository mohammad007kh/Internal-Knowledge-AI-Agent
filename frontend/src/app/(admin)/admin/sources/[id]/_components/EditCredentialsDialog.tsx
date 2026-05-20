'use client'

/**
 * EditCredentialsDialog (U8 + FX4 + FX7)
 *
 * Settings-tab affordance to rotate a database source's connection
 * credentials. Mounted from the Connection card; opened when the admin
 * clicks "Edit credentials".
 *
 * UX contract — every part of which is enforced by the backend:
 *
 *   1. On open the dialog fetches the source's non-secret connection config
 *      (`GET /sources/{id}/connection-config`) and pre-fills the visible
 *      fields (db_type / host / port / database / username / ssl_mode /
 *      collection). The password field stays EMPTY — an empty password on
 *      submit means "keep the current password". While the fetch is in
 *      flight the form is disabled; on error the admin can still fill the
 *      form from scratch (we don't hard-block — they may want to fix a
 *      broken config).
 *   2. On Save we send ONLY the fields that DIFFER from the fetched config
 *      (plus `password` if the admin typed one), so an unchanged form sends
 *      just `confirm_password` and the backend keeps everything — and the
 *      audit row's `changed_fields` stays accurate.
 *   3. A "Confirm your password" field at the bottom re-authenticates the
 *      admin (FX4). Wrong password → 401 → inline error, dialog stays open.
 *   4. On Save the backend runs Test Connection BEFORE persisting. A
 *      connector failure → 422 → we surface the error inline and the dialog
 *      stays open. On success: connection_status resets to `unknown`, the
 *      source becomes "temporarily unavailable" until the next Test
 *      Connection succeeds, the schema is re-studied, and an audit row is
 *      written.
 *
 * SECURITY
 *   - The connection-config response never includes the password or the raw
 *     connection string — only the metadata the admin already typed.
 *   - Both password fields are type=password and never echoed.
 *   - The submitted body is never console.log'd. The shared apiClient does
 *     not log request bodies on errors either.
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
import {
  sourcesKeys,
  useSourceConnectionConfig,
} from '@/features/sources/hooks/useSources'
import { extractApiErrorMessage } from '@/lib/api-error'
import {
  inspectSourceApi,
  type SourceConnectionConfig,
  type SourceDetail,
  type UpdateSourceCredentialsRequest,
  updateSourceCredentialsApi,
} from '@/lib/api/sources'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangleIcon, Loader2Icon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

// ---------------------------------------------------------------------------
// Local form state. Pre-filled from the fetched connection config on open;
// the password field stays empty (empty = "keep current"). We diff against
// the fetched config at submit time so the payload — and the backend's
// audit `changed_fields` — only contains what actually changed.
// ---------------------------------------------------------------------------

type DbType = 'postgresql' | 'mysql' | 'mssql' | 'mongodb'
type SslMode = 'disable' | 'require' | 'verify-ca' | 'verify-full'
const SSL_KEEP = '__keep__'

interface CredentialsFormState {
  db_type: DbType | ''
  host: string
  port: string
  database: string
  username: string
  ssl_mode: SslMode | typeof SSL_KEEP
  collection: string
  password: string
  confirm_password: string
}

const EMPTY_FORM: CredentialsFormState = {
  db_type: '',
  host: '',
  port: '',
  database: '',
  username: '',
  ssl_mode: SSL_KEEP,
  collection: '',
  password: '',
  confirm_password: '',
}

/** Build the initial form from a fetched config (password stays empty). */
function formFromConfig(config: SourceConnectionConfig): CredentialsFormState {
  return {
    db_type: config.db_type ?? '',
    host: config.host ?? '',
    port: config.port === null ? '' : String(config.port),
    database: config.database ?? '',
    username: config.username ?? '',
    ssl_mode: config.ssl_mode ?? SSL_KEEP,
    collection: config.collection ?? '',
    password: '',
    confirm_password: '',
  }
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

  // Fetch the non-secret connection config when the dialog is open. The
  // password is never part of this response — the form's password field
  // stays empty regardless.
  const configQuery = useSourceConnectionConfig(source.id, { enabled: open })
  const fetchedConfig = configQuery.data ?? null

  // Pre-fill the form once the config arrives. We key off the config object
  // identity so a refetch (e.g. after a rotation elsewhere) re-syncs the
  // form — but typing isn't clobbered mid-edit because React Query won't
  // hand back a new object until the next successful fetch.
  useEffect(() => {
    if (fetchedConfig) {
      setForm(formFromConfig(fetchedConfig))
      setSubmitError(null)
    }
  }, [fetchedConfig])

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
      queryClient.invalidateQueries({
        queryKey: sourcesKeys.connectionConfig(source.id),
      })
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
      // `extractApiErrorMessage` digs the backend's `detail` out of the
      // raw AxiosError (`updateSourceCredentialsApi` calls `apiClient`
      // directly, so axios's useless "Request failed with status code 422"
      // is what would otherwise reach us) — including the nested
      // `detail.detail` shape FastAPI emits for `HTTPException(detail={...})`,
      // which carries the "…Credentials were NOT updated." copy verbatim.
      setSubmitError(extractApiErrorMessage(err))
    },
  })

  const isLoadingConfig = open && configQuery.isLoading
  const formDisabled = isLoadingConfig || mutation.isPending

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitError(null)

    if (form.confirm_password.trim().length === 0) {
      setSubmitError('Confirm your password to apply changes.')
      return
    }

    // Validate the port up-front (string → number).
    let portNumber: number | null = null
    if (form.port.trim()) {
      portNumber = Number.parseInt(form.port, 10)
      if (Number.isNaN(portNumber) || portNumber < 1 || portNumber > 65535) {
        setSubmitError('Port must be a number between 1 and 65535.')
        return
      }
    }

    // Diff each visible field against the fetched config. Only fields that
    // actually changed go into the payload — that keeps the backend's audit
    // `changed_fields` accurate (it's built from the submitted keys). When
    // there's no fetched config (the fetch failed), treat every non-empty
    // field as a change so the admin can still rotate from scratch.
    const cfg = fetchedConfig
    const payload: UpdateSourceCredentialsRequest = {
      confirm_password: form.confirm_password,
    }

    const dbType = form.db_type === '' ? null : form.db_type
    if (dbType !== null && dbType !== (cfg?.db_type ?? null)) {
      payload.db_type = dbType
    }

    const host = form.host.trim() || null
    if (host !== null && host !== (cfg?.host ?? null)) payload.host = host

    if (portNumber !== null && portNumber !== (cfg?.port ?? null)) {
      payload.port = portNumber
    }

    const database = form.database.trim() || null
    if (database !== null && database !== (cfg?.database ?? null)) {
      payload.database = database
    }

    const username = form.username.trim() || null
    if (username !== null && username !== (cfg?.username ?? null)) {
      payload.username = username
    }

    const sslMode = form.ssl_mode === SSL_KEEP ? null : form.ssl_mode
    if (sslMode !== null && sslMode !== (cfg?.ssl_mode ?? null)) {
      payload.ssl_mode = sslMode
    }

    const collection = form.collection.trim() || null
    if (collection !== null && collection !== (cfg?.collection ?? null)) {
      payload.collection = collection
    }

    // Password: include ONLY if the admin typed something. Empty = keep.
    if (form.password.length > 0) payload.password = form.password

    mutation.mutate(payload)
  }

  const hasPassword = fetchedConfig?.has_password ?? false
  const passwordPlaceholder = isLoadingConfig
    ? 'Loading…'
    : hasPassword
      ? '•••••••• (unchanged) — leave blank to keep the current password'
      : 'No password set — leave blank or enter one'

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="flex max-h-[85vh] flex-col gap-0 p-0 sm:max-w-[520px]"
        data-testid="edit-credentials-dialog"
      >
        <form
          onSubmit={handleSubmit}
          className="flex min-h-0 flex-1 flex-col"
          aria-label="Edit credentials"
        >
          <div className="px-6 pt-6">
            <DialogHeader>
              <DialogTitle>Edit connection credentials</DialogTitle>
              <DialogDescription>
                Editing the connection for &ldquo;{source.name}&rdquo;. Current
                values are pre-filled. Changing host/port/database/username and
                saving will run a Test Connection first. Leave the password
                blank to keep the current one.
              </DialogDescription>
            </DialogHeader>
          </div>

          <div
            className="flex-1 space-y-4 overflow-y-auto px-6 py-4"
            data-testid="edit-credentials-scroll"
          >
            {/* Config-load error — non-fatal. The admin can still fill the
                form from scratch (useful when the stored config is broken). */}
            {configQuery.isError && (
              <p
                className="rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-xs text-amber-900 dark:text-amber-200"
                role="status"
                data-testid="edit-credentials-config-error"
              >
                Couldn&rsquo;t load the current connection settings — you can
                still enter them below.
              </p>
            )}

            {/* Stern warning — the backend resets connection_status and the
                source becomes temporarily unavailable until the next probe. */}
            <div
              role="alert"
              className="flex gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-900 dark:text-amber-200"
              data-testid="edit-credentials-warning"
            >
              <AlertTriangleIcon
                className="mt-0.5 h-4 w-4 shrink-0"
                aria-hidden
              />
              <div className="space-y-1">
                <p className="font-medium">Saving will:</p>
                <ul className="list-disc space-y-0.5 pl-4">
                  <li>
                    Reset the connection status pill to &ldquo;Unknown&rdquo;.
                  </li>
                  <li>
                    Make this source temporarily unavailable to chat users
                    until a Test Connection succeeds.
                  </li>
                  <li>Re-study the database schema in the background.</li>
                  <li>Write an audit log entry naming you as the editor.</li>
                  <li>
                    Run a Test Connection FIRST — if it fails, nothing is
                    saved.
                  </li>
                </ul>
              </div>
            </div>

            <fieldset disabled={formDisabled} className="space-y-4">
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
                    <SelectValue placeholder="Select type" />
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
                <Label htmlFor="ssl_mode">SSL mode</Label>
                <Select
                  value={form.ssl_mode}
                  onValueChange={(v) =>
                    setForm((f) => ({
                      ...f,
                      ssl_mode: v as CredentialsFormState['ssl_mode'],
                    }))
                  }
                >
                  <SelectTrigger id="ssl_mode" data-testid="cred-ssl-mode">
                    <SelectValue placeholder="SSL mode" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={SSL_KEEP}>Keep current</SelectItem>
                    <SelectItem value="disable">disable</SelectItem>
                    <SelectItem value="require">require</SelectItem>
                    <SelectItem value="verify-ca">verify-ca</SelectItem>
                    <SelectItem value="verify-full">verify-full</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="col-span-2 space-y-1.5">
                <Label htmlFor="collection">Collection (MongoDB)</Label>
                <Input
                  id="collection"
                  autoComplete="off"
                  value={form.collection}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, collection: e.target.value }))
                  }
                  data-testid="cred-collection"
                />
              </div>

              <div className="col-span-2 space-y-1.5">
                <Label htmlFor="password">New password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  placeholder={passwordPlaceholder}
                  value={form.password}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, password: e.target.value }))
                  }
                  data-testid="cred-password"
                />
                <p
                  className="text-xs text-muted-foreground"
                  data-testid="cred-password-help"
                >
                  {hasPassword
                    ? 'A password is currently stored. Leave blank to keep it; enter a new one to rotate.'
                    : 'No password is currently stored. Leave blank or enter one.'}
                </p>
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
                Required. Re-authenticates you before this credential change
                is applied.
              </p>
            </div>
            </fieldset>

            {submitError !== null && (
              <p
                className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive"
                role="alert"
                data-testid="edit-credentials-error"
              >
                {submitError}
              </p>
            )}
          </div>

          <div className="border-t px-6 py-4">
            <DialogFooter className="gap-2 sm:gap-2">
              <TestCredentialsButton
                form={form}
                disabled={formDisabled}
              />
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
                disabled={formDisabled}
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
                ) : isLoadingConfig ? (
                  <>
                    <Loader2Icon
                      className="mr-1.5 h-4 w-4 animate-spin"
                      aria-hidden
                    />
                    Loading…
                  </>
                ) : (
                  <>Test &amp; save</>
                )}
              </Button>
            </DialogFooter>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// TestCredentialsButton (FX30)
//
// Local "Test connection" affordance for the edit-credentials modal. Mirrors
// the canonical TestConnectionButton in the new-source wizard
// (frontend/src/app/(admin)/admin/sources/new/page.tsx) but reads from this
// dialog's local form state instead of react-hook-form, and lives in the
// dialog footer (left side) so it sits next to Save/Cancel.
//
// Contract:
//   - Builds an InspectSourceRequest from the current form values.
//   - Always sends db_type/host/port/database/username/password.
//   - Sends `ssl_mode` ONLY when the admin picked a real value (the
//     "Keep current" SSL_KEEP sentinel is dialog-local — backend doesn't
//     know it).
//   - Sends `collection` ONLY for MongoDB.
//   - Requires a real password — the SSL_KEEP/empty-password "keep current"
//     sentinel cannot be tested (the backend needs the actual password to
//     attempt a connection). The button is disabled with a tooltip until
//     the admin types one.
//   - Surfaces success / failure as a toast using extractApiErrorMessage so
//     the backend's RFC-7807 `detail` (e.g. 'password authentication failed
//     for user "cctp"') is shown verbatim.
// ---------------------------------------------------------------------------

interface TestCredentialsButtonProps {
  form: CredentialsFormState
  disabled: boolean
}

function TestCredentialsButton({ form, disabled }: TestCredentialsButtonProps) {
  const allRequiredFilled =
    form.db_type !== '' &&
    form.host.trim().length > 0 &&
    form.port.trim().length > 0 &&
    form.database.trim().length > 0 &&
    form.username.trim().length > 0 &&
    form.password.length > 0

  const mutation = useMutation({
    mutationFn: async () => {
      const portValue = Number.parseInt(form.port, 10)
      const connection: Record<string, unknown> = {
        db_type: form.db_type,
        host: form.host.trim(),
        port: Number.isFinite(portValue) ? portValue : form.port,
        database: form.database.trim(),
        username: form.username.trim(),
        password: form.password,
      }
      if (form.ssl_mode !== SSL_KEEP) {
        connection.ssl_mode = form.ssl_mode
      }
      if (form.db_type === 'mongodb' && form.collection.trim().length > 0) {
        connection.collection = form.collection.trim()
      }
      return inspectSourceApi({ source_type: 'database', connection })
    },
    onSuccess: (data) => {
      const description = data?.description?.trim() ?? ''
      toast.success(
        description.length > 0 ? description : 'Connection successful.'
      )
    },
    onError: (err) => {
      toast.error(extractApiErrorMessage(err))
    },
  })

  const buttonDisabled = disabled || !allRequiredFilled || mutation.isPending
  const tooltip = !allRequiredFilled
    ? 'Enter the password to test the connection'
    : undefined

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="mr-auto"
      onClick={() => mutation.mutate()}
      disabled={buttonDisabled}
      title={tooltip}
      aria-label="Test connection"
      data-testid="edit-credentials-test"
    >
      {mutation.isPending ? (
        <>
          <Loader2Icon className="mr-1.5 h-4 w-4 animate-spin" aria-hidden />
          Testing…
        </>
      ) : (
        'Test connection'
      )}
    </Button>
  )
}
