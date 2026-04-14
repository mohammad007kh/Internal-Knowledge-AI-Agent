'use client'

import { Button } from '@/components/ui/button'
import { useAuth } from '@/features/auth/context/AuthContext'
import { KeyRoundIcon, MailIcon, ShieldCheckIcon, UserIcon } from 'lucide-react'
import Link from 'next/link'

export default function ProfilePage() {
  const { user } = useAuth()

  if (!user) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-muted-foreground">Loading profile…</p>
      </div>
    )
  }

  return (
    <div className="space-y-6 p-6">
      <h1 className="text-xl font-semibold">Profile</h1>

      <div className="rounded-lg border border-border bg-card p-6 space-y-4 max-w-md">
        <div className="flex items-center gap-3">
          <MailIcon className="h-4 w-4 text-muted-foreground" />
          <div>
            <p className="text-xs text-muted-foreground">Email</p>
            <p className="text-sm font-medium">{user.email}</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <UserIcon className="h-4 w-4 text-muted-foreground" />
          <div>
            <p className="text-xs text-muted-foreground">Full name</p>
            <p className="text-sm font-medium">
              {user.full_name ?? '—'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <ShieldCheckIcon className="h-4 w-4 text-muted-foreground" />
          <div>
            <p className="text-xs text-muted-foreground">Role</p>
            <p className="text-sm font-medium capitalize">{user.role}</p>
          </div>
        </div>
      </div>

      <div>
        <Button asChild variant="outline" size="sm">
          <Link href="/auth/change-password">
            <KeyRoundIcon className="mr-2 h-4 w-4" />
            Change Password
          </Link>
        </Button>
      </div>
    </div>
  )
}
