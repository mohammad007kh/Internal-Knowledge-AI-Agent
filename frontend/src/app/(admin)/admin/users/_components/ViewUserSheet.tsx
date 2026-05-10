'use client'

import type { AdminUser } from '@/components/admin/UsersTable'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { usersKeys } from '@/features/users/hooks/useUsersQueries'
import { apiClient } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import { useQuery } from '@tanstack/react-query'
import { BanIcon, CheckCircleIcon, ShieldCheckIcon, UserIcon } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import { UserDangerZone } from './UserDangerZone'
import { UserProfileSection } from './UserProfileSection'
import { UserRoleSection } from './UserRoleSection'
import { UserSecuritySection } from './UserSecuritySection'

/**
 * ViewUserSheet
 * ------------------------------------------------------------
 * Right-side Sheet (sm:max-w-xl). Reads `?user=<id>` from the
 * URL — the sheet is the source-of-truth view of a user, so it
 * is deeplinkable, refresh-safe, and back-button closes.
 *
 * Layout:
 *   - Avatar header + state chips (Active/Inactive, role) + last seen
 *   - PROFILE (per-field inline edit)
 *   - ROLE & ACCESS (dedicated Save, audited PATCH /role)
 *   - SECURITY (admin-trigger reset)
 *   - DANGER ZONE (deactivate / delete with email confirm)
 */

function getInitials(input: string | null | undefined, fallback: string): string {
  const source = (input ?? fallback).trim()
  if (!source) return '?'
  const parts = source.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase()
  }
  return source.slice(0, 2).toUpperCase()
}

function formatLastSeen(iso: string | null): string {
  if (!iso) return 'Never signed in'
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return 'Never signed in'
  const deltaMs = Date.now() - t.getTime()
  const min = Math.round(deltaMs / 60000)
  if (min < 1) return 'Last seen just now'
  if (min < 60) return `Last seen ${min} min ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `Last seen ${hr}h ago`
  const days = Math.round(hr / 24)
  if (days < 30) return `Last seen ${days}d ago`
  return `Last seen ${t.toLocaleDateString()}`
}

async function getUserApi(id: string): Promise<AdminUser> {
  const res = await apiClient.get<AdminUser>(`/api/v1/users/${id}`)
  return res.data
}

export function ViewUserSheet() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const userId = searchParams.get('user')

  const closeSheet = () => {
    // Drop only the ?user param, preserve the page.
    router.replace('/admin/users')
  }

  const isOpen = Boolean(userId)

  const { data: user, isLoading, isError } = useQuery({
    queryKey: usersKeys.detail(userId ?? ''),
    queryFn: () => getUserApi(userId as string),
    enabled: isOpen,
  })

  return (
    <Sheet open={isOpen} onOpenChange={(o) => !o && closeSheet()}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 p-0 sm:max-w-xl"
        aria-describedby={undefined}
      >
        {isLoading || !user ? (
          <SheetLoadingOrError isError={isError} onClose={closeSheet} />
        ) : (
          <>
            {/* Header */}
            <div className="border-b p-5">
              <div className="flex items-start gap-3">
                <div
                  className={cn(
                    'flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-base font-semibold',
                    user.is_active
                      ? 'bg-primary/15 text-primary'
                      : 'bg-muted text-muted-foreground'
                  )}
                  aria-hidden
                >
                  {getInitials(user.full_name, user.email)}
                </div>
                <div className="min-w-0 flex-1">
                  <SheetTitle className="truncate text-base font-semibold leading-tight">
                    {user.full_name ?? user.email}
                  </SheetTitle>
                  <SheetDescription className="mt-0.5 truncate text-sm">
                    {user.email}
                  </SheetDescription>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Badge
                      variant="outline"
                      className={cn(
                        'gap-1',
                        user.is_active
                          ? 'border-green-500/50 text-green-700 dark:text-green-400'
                          : 'border-muted-foreground/30 text-muted-foreground'
                      )}
                    >
                      {user.is_active ? (
                        <CheckCircleIcon className="h-3 w-3" aria-hidden />
                      ) : (
                        <BanIcon className="h-3 w-3" aria-hidden />
                      )}
                      {user.is_active ? 'Active' : 'Inactive'}
                    </Badge>
                    <Badge
                      variant={user.role === 'admin' ? 'default' : 'secondary'}
                      className="gap-1 capitalize"
                    >
                      {user.role === 'admin' ? (
                        <ShieldCheckIcon className="h-3 w-3" aria-hidden />
                      ) : (
                        <UserIcon className="h-3 w-3" aria-hidden />
                      )}
                      {user.role === 'admin' ? 'Admin' : 'Member'}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {formatLastSeen(user.last_login_at)}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* Sections */}
            <div className="flex-1 space-y-5 overflow-y-auto p-5">
              <UserProfileSection
                userId={user.id}
                fullName={user.full_name}
                email={user.email}
                createdAt={user.created_at}
              />

              <UserRoleSection userId={user.id} currentRole={user.role} />

              <UserSecuritySection userId={user.id} />

              <div className="border-t pt-5">
                <UserDangerZone
                  userId={user.id}
                  email={user.email}
                  isActive={user.is_active}
                  onDeleted={closeSheet}
                />
              </div>
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  )
}

function SheetLoadingOrError({
  isError,
  onClose,
}: {
  isError: boolean
  onClose: () => void
}) {
  if (isError) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-6 text-center">
        <SheetTitle className="text-base text-destructive">Failed to load user</SheetTitle>
        <SheetDescription>The user may have been removed or the link is stale.</SheetDescription>
        <Button variant="outline" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    )
  }
  return (
    <div className="space-y-4 p-5" aria-busy="true">
      <SheetTitle className="sr-only">Loading user</SheetTitle>
      <div className="flex items-center gap-3">
        <Skeleton className="h-12 w-12 rounded-full" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-3 w-1/3" />
        </div>
      </div>
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-16 w-full" />
      <Skeleton className="h-16 w-full" />
    </div>
  )
}
