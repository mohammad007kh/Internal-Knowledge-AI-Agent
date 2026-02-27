'use client'

import { Shield, ShieldOff, Trash2, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuth } from '@/features/auth/context/AuthContext'
import { InviteUserModal } from '@/features/users/components/InviteUserModal'
import {
  useChangeRole,
  useDeactivateUser,
  useUsersList,
} from '@/features/users/hooks/useUsersQueries'

const SKELETON_ROWS = ['a', 'b', 'c', 'd', 'e'] as const
const SKELETON_COLS = ['col1', 'col2', 'col3', 'col4', 'col5'] as const

const PAGE_SIZE = 50

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth()
  const [offset, setOffset] = useState(0)
  const [inviteOpen, setInviteOpen] = useState(false)
  const [confirmDeactivate, setConfirmDeactivate] = useState<string | null>(null)

  const { data, isLoading, error } = useUsersList(PAGE_SIZE, offset)
  const changeRole = useChangeRole()
  const deactivate = useDeactivateUser()

  const handleChangeRole = async (userId: string, currentRole: 'admin' | 'user') => {
    const newRole = currentRole === 'admin' ? 'user' : 'admin'
    try {
      await changeRole.mutateAsync({ userId, body: { role: newRole } })
      toast.success(`Role changed to ${newRole}`)
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to change role'
      toast.error(message)
    }
  }

  const handleDeactivate = async (userId: string) => {
    try {
      await deactivate.mutateAsync(userId)
      toast.success('User deactivated')
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Failed to deactivate user'
      toast.error(message)
    } finally {
      setConfirmDeactivate(null)
    }
  }

  if (error) {
    return (
      <div className="p-6">
        <p className="text-destructive">Failed to load users. Please refresh.</p>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Users</h1>
          {data && (
            <p className="text-sm text-muted-foreground">
              {data.total} total user{data.total !== 1 ? 's' : ''}
            </p>
          )}
        </div>
        <Button onClick={() => setInviteOpen(true)} size="sm">
          <UserPlus className="mr-2 h-4 w-4" />
          Invite user
        </Button>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Joined</TableHead>
              <TableHead className="w-[120px]">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading
              ? SKELETON_ROWS.map((rowId) => (
                  <TableRow key={rowId}>
                    {SKELETON_COLS.map((colId) => (
                      <TableCell key={colId}>
                        <div className="h-4 w-full animate-pulse rounded bg-muted" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              : data?.items.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-mono text-sm">{u.email}</TableCell>
                    <TableCell>
                      <Badge variant={u.role === 'admin' ? 'default' : 'secondary'}>{u.role}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={u.is_active ? 'outline' : 'destructive'}>
                        {u.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {new Date(u.created_at).toLocaleDateString()}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Change role for ${u.email}`}
                          disabled={changeRole.isPending}
                          onClick={() => handleChangeRole(u.id, u.role)}
                        >
                          {u.role === 'admin' ? (
                            <ShieldOff className="h-4 w-4" />
                          ) : (
                            <Shield className="h-4 w-4" />
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Deactivate ${u.email}`}
                          disabled={!u.is_active || u.id === currentUser?.id}
                          onClick={() => setConfirmDeactivate(u.id)}
                          className="text-destructive hover:text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
          </TableBody>
        </Table>
      </div>

      {data && data.total > PAGE_SIZE && (
        <div className="flex justify-end gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={offset + PAGE_SIZE >= data.total}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
          >
            Next
          </Button>
        </div>
      )}

      <InviteUserModal open={inviteOpen} onClose={() => setInviteOpen(false)} />

      <AlertDialog
        open={!!confirmDeactivate}
        onOpenChange={(o) => !o && setConfirmDeactivate(null)}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Deactivate user?</AlertDialogTitle>
            <AlertDialogDescription>
              This will prevent the user from signing in. Their data will be retained. This action
              can be reversed by a database administrator.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => confirmDeactivate && handleDeactivate(confirmDeactivate)}
            >
              Deactivate
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
