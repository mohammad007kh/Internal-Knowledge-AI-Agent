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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { SegmentedControl } from '@/components/ui/segmented-control'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useAuth } from '@/features/auth/context/AuthContext'
import { useDeactivateUser, useReactivateUser, useUsersList } from '@/features/users/hooks/useUsersQueries'
import type { UserListItem, UserStatusFilter } from '@/lib/api/users'
import { cn } from '@/lib/utils'
import { type ColumnDef, flexRender, getCoreRowModel, useReactTable } from '@tanstack/react-table'
import {
  BanIcon,
  CheckCircleIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  PencilIcon,
  ShieldCheckIcon,
  UserIcon,
} from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

const PAGE_SIZE = 25

const STATUS_OPTIONS: ReadonlyArray<{ value: UserStatusFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'inactive', label: 'Deactivated' },
]

export function UsersTable() {
  const router = useRouter()
  const { user: authUser } = useAuth()
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState<'all' | 'admin' | 'user'>('all')
  const [statusFilter, setStatusFilter] = useState<UserStatusFilter>('all')
  const [deactivatingId, setDeactivatingId] = useState<string | null>(null)

  const { data, isLoading } = useUsersList({ page, pageSize: PAGE_SIZE, status: statusFilter })

  const deactivate = useDeactivateUser()
  const reactivate = useReactivateUser()

  // Server-side pagination + status filter; role + free-text search remain
  // client-side over the current page (a deliberate scope choice — the
  // page is at most PAGE_SIZE rows).
  const pageItems: UserListItem[] = useMemo(() => data?.items ?? [], [data?.items])
  const users = useMemo(() => {
    const term = search.trim().toLowerCase()
    return pageItems.filter((u) => {
      const matchRole = roleFilter === 'all' || u.role === roleFilter
      const matchSearch =
        term.length === 0 ||
        u.email.toLowerCase().includes(term) ||
        (u.full_name?.toLowerCase().includes(term) ?? false)
      return matchRole && matchSearch
    })
  }, [pageItems, roleFilter, search])

  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  // Snap back to page 1 whenever the server-side filter changes so we never
  // request a page past the (new) end of the result set.
  useEffect(() => {
    setPage(1)
  }, [statusFilter])

  // Clamp the current page if the result set shrank under us (e.g. another
  // admin reactivated users while this list was open).
  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const handleDeactivate = (id: string): void => {
    deactivate.mutate(id, {
      onSuccess: () => {
        toast.success('User deactivated.')
        setDeactivatingId(null)
      },
      onError: () => toast.error('Failed to deactivate user.'),
    })
  }

  const handleReactivate = (id: string): void => {
    reactivate.mutate(id, {
      onSuccess: () => toast.success('User reactivated.'),
      onError: () => toast.error('Failed to reactivate user.'),
    })
  }

  const columns: ColumnDef<UserListItem>[] = [
    {
      accessorKey: 'email',
      header: 'Email',
      cell: ({ row }) => (
        <button
          type="button"
          onClick={() => router.push(`/admin/users?user=${row.original.id}`)}
          className="block max-w-[180px] truncate text-left font-medium hover:underline sm:max-w-[260px]"
          title={row.original.email}
        >
          {row.original.email}
        </button>
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
        return active ? (
          <Badge
            variant="outline"
            className="gap-1 border-green-500 text-green-700 dark:text-green-400"
          >
            <CheckCircleIcon className="h-3 w-3" />
            Active
          </Badge>
        ) : (
          <Badge variant="outline" className="gap-1 text-muted-foreground">
            <BanIcon className="h-3 w-3" />
            Deactivated
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
            className="h-9 w-9"
            onClick={() => router.push(`/admin/users?user=${row.original.id}`)}
            aria-label={`Edit ${row.original.email}`}
          >
            <PencilIcon className="h-4 w-4" />
          </Button>
          {row.original.is_active ? (
            row.original.id !== authUser?.id ? (
              <Button
                size="icon"
                variant="ghost"
                className="h-9 w-9 text-destructive hover:bg-destructive/10"
                onClick={() => setDeactivatingId(row.original.id)}
                aria-label={`Deactivate ${row.original.email}`}
              >
                <BanIcon className="h-4 w-4" />
              </Button>
            ) : null
          ) : (
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1 text-green-700 dark:text-green-400"
              onClick={() => handleReactivate(row.original.id)}
              disabled={reactivate.isPending}
              aria-label={`Reactivate ${row.original.email}`}
            >
              <CheckCircleIcon className="h-3.5 w-3.5" />
              Reactivate
            </Button>
          )}
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

  const showFooter = total > PAGE_SIZE

  return (
    <>
      <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
        <Input
          placeholder="Search by email or name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="h-9 w-full sm:max-w-xs"
          aria-label="Search users"
        />
        <div className="flex flex-wrap items-center gap-2">
          <SegmentedControl<UserStatusFilter>
            label="Status"
            options={STATUS_OPTIONS}
            value={statusFilter}
            onChange={setStatusFilter}
          />
          <Select value={roleFilter} onValueChange={(v) => setRoleFilter(v as typeof roleFilter)}>
            <SelectTrigger className="h-9 flex-1 sm:w-36 sm:flex-none" aria-label="Filter by role">
              <SelectValue placeholder="All roles" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All roles</SelectItem>
              <SelectItem value="admin">Admin</SelectItem>
              <SelectItem value="user">User</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="overflow-x-auto rounded-md border border-border">
        <Table className="min-w-[640px]">
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
                <TableRow
                  key={row.id}
                  className={cn(
                    'cursor-pointer',
                    !row.original.is_active && 'bg-muted/40 text-muted-foreground'
                  )}
                  onClick={(e) => {
                    // Ignore clicks that originated on interactive children
                    // (buttons, links, inputs) — those handle navigation /
                    // mutations themselves and shouldn't double-fire.
                    const target = e.target as HTMLElement | null
                    if (
                      target?.closest(
                        'button, a, input, [role="menuitem"], [role="menu"]'
                      )
                    ) {
                      return
                    }
                    router.push(`/admin/users?user=${row.original.id}`)
                  }}
                >
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

      {showFooter ? (
        <div className="flex items-center justify-between pt-2">
          <p className="text-xs text-muted-foreground tabular-nums">
            {total} users total — page {page} of {totalPages}
          </p>
          <div className="flex gap-1.5">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              aria-label="Previous page"
            >
              <ChevronLeftIcon className="mr-1 h-3.5 w-3.5" aria-hidden />
              Previous
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              aria-label="Next page"
            >
              Next
              <ChevronRightIcon className="ml-1 h-3.5 w-3.5" aria-hidden />
            </Button>
          </div>
        </div>
      ) : null}

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
              disabled={deactivate.isPending}
              onClick={() => deactivatingId && handleDeactivate(deactivatingId)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deactivate.isPending ? 'Deactivating…' : 'Deactivate'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  )
}
