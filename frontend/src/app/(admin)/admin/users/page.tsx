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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { UsersTable } from '@/components/admin/UsersTable'
import { usersKeys } from '@/features/users/hooks/useUsersQueries'
import { apiClient } from '@/lib/api-client'
import { getErrorMessage } from '@/lib/errors'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MailIcon, PlusIcon, Trash2Icon } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'

interface Invitation {
  id: string
  email: string
  role: 'admin' | 'user'
  expires_at: string
  created_at: string
  invited_by_email?: string | null
}

interface InvitationsResponse {
  items: Invitation[]
  total: number
}

async function listInvitations(): Promise<Invitation[]> {
  const { data } = await apiClient.get<InvitationsResponse>('/api/v1/users/invitations')
  return data.items ?? []
}

async function revokeInvitation(id: string): Promise<void> {
  await apiClient.delete(`/api/v1/users/invitations/${id}`)
}

function useInvitations() {
  return useQuery({ queryKey: usersKeys.invitations(), queryFn: listInvitations })
}

function useRevokeInvitation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: revokeInvitation,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: usersKeys.invitations() })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
      toast.success('Invitation revoked')
    },
    onError: (err) => toast.error(getErrorMessage(err)),
  })
}

function InvitationsTable() {
  const { data: invitations, isLoading } = useInvitations()
  const revoke = useRevokeInvitation()
  const [revokingId, setRevokingId] = useState<string | null>(null)

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    )
  }

  if (!invitations?.length) {
    return (
      <div className="flex flex-col items-center gap-3 py-12 text-center">
        <MailIcon className="h-8 w-8 text-muted-foreground/50" aria-hidden />
        <div className="space-y-1">
          <p className="font-medium">No pending invitations</p>
          <p className="text-sm text-muted-foreground">
            Invite teammates to give them access to the knowledge base.
          </p>
        </div>
        <Button asChild size="sm" className="mt-2">
          <Link href="/admin/users/new">
            <PlusIcon className="mr-1.5 h-4 w-4" />
            Invite user
          </Link>
        </Button>
      </div>
    )
  }

  return (
    <>
      <div className="overflow-x-auto rounded-md border">
        <Table className="min-w-[640px]">
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead className="hidden md:table-cell">Invited by</TableHead>
              <TableHead>Expires</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {invitations.map((inv) => (
              <TableRow key={inv.id}>
                <TableCell className="max-w-[180px] truncate font-medium" title={inv.email}>
                  {inv.email}
                </TableCell>
                <TableCell>
                  <Badge
                    variant="outline"
                    className={
                      inv.role === 'admin'
                        ? 'border-purple-500/30 bg-purple-500/10 text-purple-700 dark:text-purple-300'
                        : 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-300'
                    }
                  >
                    {inv.role}
                  </Badge>
                </TableCell>
                <TableCell className="hidden text-sm text-muted-foreground md:table-cell">
                  {inv.invited_by_email ?? '—'}
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {new Date(inv.expires_at).toLocaleDateString()}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="text-destructive hover:text-destructive"
                    onClick={() => setRevokingId(inv.id)}
                    aria-label={`Revoke invitation for ${inv.email}`}
                  >
                    <Trash2Icon className="mr-1 h-4 w-4" />
                    <span className="hidden sm:inline">Revoke</span>
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <AlertDialog open={!!revokingId} onOpenChange={(o) => !o && setRevokingId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke invitation?</AlertDialogTitle>
            <AlertDialogDescription>
              The invite link will stop working immediately. The user will need to be re-invited.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={() => {
                if (revokingId) {
                  revoke.mutate(revokingId, { onSettled: () => setRevokingId(null) })
                }
              }}
            >
              Revoke
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}

export default function UsersPage() {
  const { data: invitations } = useInvitations()
  const pendingCount = invitations?.length ?? 0

  return (
    <div className="space-y-4 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Users</h1>
        <Button asChild size="sm" className="w-full sm:w-auto">
          <Link href="/admin/users/new">
            <PlusIcon className="mr-1.5 h-4 w-4" />
            Invite user
          </Link>
        </Button>
      </div>

      <Tabs defaultValue="users">
        <TabsList>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="invitations">
            Invitations
            {pendingCount > 0 && (
              <Badge
                variant="secondary"
                className="ml-2 h-5 min-w-5 px-1.5 text-xs tabular-nums"
              >
                {pendingCount}
              </Badge>
            )}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="users" className="mt-4">
          <UsersTable />
        </TabsContent>
        <TabsContent value="invitations" className="mt-4">
          <InvitationsTable />
        </TabsContent>
      </Tabs>
    </div>
  )
}
