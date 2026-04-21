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
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuth } from '@/features/auth/context/AuthContext'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import { BanIcon, CheckCircleIcon, PencilIcon, ShieldCheckIcon, UserIcon } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'

export interface AdminUser {
  id: string
  email: string
  full_name: string | null
  role: 'admin' | 'user'
  is_active: boolean
  last_login_at: string | null
  created_at: string
}

interface UsersResponse {
  items: AdminUser[]
  total: number
  page: number
  page_size: number
}

const PAGE_SIZE = 25

async function fetchUsers(page: number, search: string): Promise<UsersResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(PAGE_SIZE),
  })
  if (search) params.set('search', search)
  const res = await apiClient.get<UsersResponse>(`/api/v1/admin/users?${params}`)
  return res.data
}

async function deactivateUser(id: string): Promise<void> {
  await apiClient.patch(`/api/v1/admin/users/${id}`, { is_active: false })
}

async function reactivateUser(id: string): Promise<void> {
  await apiClient.patch(`/api/v1/admin/users/${id}`, { is_active: true })
}

export function UsersTable() {
  const queryClient = useQueryClient()
  const { user: authUser } = useAuth()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [deactivatingId, setDeactivatingId] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['admin-users', page, search],
    queryFn: () => fetchUsers(page, search),
    staleTime: 15_000,
  })

  const users: AdminUser[] = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.ceil(total / PAGE_SIZE)

  const deactivateMutation = useMutation({
    mutationFn: deactivateUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      setDeactivatingId(null)
      toast.success('User deactivated.')
    },
    onError: () => toast.error('Failed to deactivate user.'),
  })

  const reactivateMutation = useMutation({
    mutationFn: reactivateUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      toast.success('User reactivated.')
    },
    onError: () => toast.error('Failed to reactivate user.'),
  })

  const columns: ColumnDef<AdminUser>[] = [
    {
      accessorKey: 'email',
      header: 'Email',
      cell: ({ row }) => (
        <Link href={`/admin/users/${row.original.id}`} className="font-medium hover:underline">
          {row.original.email}
        </Link>
      ),
    },
    {
      accessorKey: 'full_name',
      header: 'Name',
      cell: ({ getValue }) => (
        <span className="text-sm text-muted-foreground">
          {(getValue() as string | null) ?? '—'}
        </span>
      ),
    },
    {
      accessorKey: 'role',
      header: 'Role',
      cell: ({ getValue }) => {
        const role = getValue() as 'admin' | 'user'
        return (
          <Badge variant={role === 'admin' ? 'default' : 'secondary'} className="gap-1">
            {role === 'admin' ? (
              <ShieldCheckIcon className="h-3 w-3" />
            ) : (
              <UserIcon className="h-3 w-3" />
            )}
            {role}
          </Badge>
        )
      },
    },
    {
      accessorKey: 'is_active',
      header: 'Status',
      cell: ({ getValue }) => {
        const active = getValue() as boolean
        return (
          <Badge
            variant={active ? 'outline' : 'secondary'}
            className={cn(
              'gap-1',
              active ? 'border-green-500 text-green-700 dark:text-green-400' : ''
            )}
          >
            {active ? <CheckCircleIcon className="h-3 w-3" /> : <BanIcon className="h-3 w-3" />}
            {active ? 'Active' : 'Inactive'}
          </Badge>
        )
      },
    },
    {
      accessorKey: 'last_login_at',
      header: 'Last login',
      cell: ({ getValue }) => {
        const v = getValue() as string | null
        return (
          <span className="text-xs text-muted-foreground">
            {v ? new Date(v).toLocaleString() : 'Never'}
          </span>
        )
      },
    },
    {
      id: 'actions',
      header: '',
      cell: ({ row }) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            asChild
            aria-label={`Edit ${row.original.email}`}
          >
            <Link href={`/admin/users/${row.original.id}`}>
              <PencilIcon className="h-3.5 w-3.5" />
            </Link>
          </Button>
          {row.original.is_active && row.original.id !== authUser?.id ? (
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7 text-destructive hover:bg-destructive/10"
              onClick={() => setDeactivatingId(row.original.id)}
              aria-label={`Deactivate ${row.original.email}`}
            >
              <BanIcon className="h-3.5 w-3.5" />
            </Button>
          ) : !row.original.is_active ? (
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7 text-green-600"
              onClick={() => reactivateMutation.mutate(row.original.id)}
              disabled={reactivateMutation.isPending}
              aria-label={`Reactivate ${row.original.email}`}
            >
              <CheckCircleIcon className="h-3.5 w-3.5" />
            </Button>
          ) : null}
        </div>
      ),
    },
  ]

  const table = useReactTable({
    data: users,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: totalPages,
  })

  return (
    <>
      <div className="mb-3 max-w-xs">
        <Input
          placeholder="Search by email or name…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
          className="h-8 text-xs"
          aria-label="Search users"
        />
      </div>

      <div className="rounded-md border border-border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((header) => (
                  <TableHead key={header.id}>
                    {header.isPlaceholder
                      ? null
                      : flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {isLoading ? (
              ['sk-r0', 'sk-r1', 'sk-r2', 'sk-r3', 'sk-r4'].map((skKey) => (
                <TableRow key={skKey}>
                  <TableCell colSpan={columns.length}>
                    <div className="h-4 animate-pulse rounded bg-muted" />
                  </TableCell>
                </TableRow>
              ))
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="py-8 text-center text-sm text-muted-foreground"
                >
                  No users found.
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <p className="text-xs text-muted-foreground">{total} users total</p>
          <div className="flex gap-1.5">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
            >
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      <AlertDialog open={!!deactivatingId} onOpenChange={(o) => !o && setDeactivatingId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Deactivate user?</AlertDialogTitle>
            <AlertDialogDescription>
              The user&apos;s access will be revoked immediately. They will be unable to log in
              until reactivated.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deactivatingId && deactivateMutation.mutate(deactivatingId)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Deactivate
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
