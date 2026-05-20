'use client'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { usersKeys } from '@/features/users/hooks/useUsersQueries'
import { apiClient } from '@/lib/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { toast } from 'sonner'

/**
 * UserDangerZone
 * ------------------------------------------------------------
 * Two destructive actions:
 *
 *   1. Disable / Re-enable  -> PATCH /users/{id} { is_active }
 *   2. Delete (soft-delete) -> DELETE /users/{id}, gated by an
 *      AlertDialog that requires typing the user's email.
 */

interface UserDangerZoneProps {
  userId: string
  email: string
  isActive: boolean
  /** Called after a successful delete so the host can close the sheet. */
  onDeleted?: () => void
}

export function UserDangerZone({
  userId,
  email,
  isActive,
  onDeleted,
}: UserDangerZoneProps) {
  const queryClient = useQueryClient()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [emailConfirm, setEmailConfirm] = useState('')
  const confirmFieldId = useId()

  const toggleActive = useMutation({
    mutationFn: (active: boolean) =>
      apiClient.patch(`/api/v1/users/${userId}`, { is_active: active }),
    onSuccess: (_data, active) => {
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
      toast.success(active ? 'User reactivated.' : 'User deactivated.')
    },
    onError: (err: unknown) => {
      const message =
        err instanceof Error ? err.message : 'Failed to update activation status'
      toast.error(message)
    },
  })

  const deleteUser = useMutation({
    mutationFn: () => apiClient.delete(`/api/v1/users/${userId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
      toast.success(`${email} deleted.`)
      setConfirmOpen(false)
      setEmailConfirm('')
      onDeleted?.()
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : 'Failed to delete user'
      toast.error(message)
    },
  })

  const canConfirmDelete = emailConfirm.trim().toLowerCase() === email.toLowerCase()

  return (
    <section aria-label="Danger zone" className="space-y-2">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-destructive">
        Danger zone
      </h3>
      <div className="divide-y rounded-md border border-destructive/30">
        {/* Disable / Re-enable */}
        <div className="flex flex-wrap items-start justify-between gap-3 p-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{isActive ? 'Deactivate' : 'Reactivate'}</p>
            <p className="text-xs text-muted-foreground">
              {isActive
                ? 'Revokes sessions, blocks login.'
                : 'Restores login. Existing sessions remain revoked.'}
            </p>
          </div>
          <Button
            type="button"
            size="sm"
            variant={isActive ? 'outline' : 'default'}
            disabled={toggleActive.isPending}
            onClick={() => toggleActive.mutate(!isActive)}
            className={
              isActive
                ? 'border-destructive/50 text-destructive hover:bg-destructive/10 hover:text-destructive'
                : ''
            }
          >
            {toggleActive.isPending
              ? 'Saving…'
              : isActive
                ? 'Disable'
                : 'Enable'}
          </Button>
        </div>

        {/* Delete */}
        <div className="flex flex-wrap items-start justify-between gap-3 p-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">Delete</p>
            <p className="text-xs text-muted-foreground">Permanently removes all data.</p>
          </div>
          <Button
            type="button"
            size="sm"
            variant="destructive"
            onClick={() => {
              setEmailConfirm('')
              setConfirmOpen(true)
            }}
          >
            Delete
          </Button>
        </div>
      </div>

      <AlertDialog
        open={confirmOpen}
        onOpenChange={(o) => {
          setConfirmOpen(o)
          if (!o) setEmailConfirm('')
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete user?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes <span className="font-medium">{email}</span> and all
              their data. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-2">
            <Label htmlFor={confirmFieldId} className="text-sm">
              Type <span className="font-mono text-foreground">{email}</span> to confirm
            </Label>
            <Input
              id={confirmFieldId}
              value={emailConfirm}
              onChange={(e) => setEmailConfirm(e.target.value)}
              placeholder={email}
              autoComplete="off"
              spellCheck={false}
              aria-label="Type the email address to confirm deletion"
            />
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={!canConfirmDelete || deleteUser.isPending}
              onClick={(e) => {
                e.preventDefault()
                if (canConfirmDelete) deleteUser.mutate()
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteUser.isPending ? 'Deleting…' : 'Delete user'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}
