'use client'

import { ThemeToggle } from '@/components/theme-toggle'
import { useAuth } from '@/features/auth/context/AuthContext'
import { useLogout } from '@/features/auth/hooks/useAuthMutations'
import { useNetworkStatus } from '@/hooks/use-network-status'
import {
  DatabaseIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  MessageCircleIcon,
  PlugIcon,
  UserCircleIcon,
  UsersIcon,
} from 'lucide-react'
import Link from 'next/link'

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const logoutMutation = useLogout()
  useNetworkStatus()

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar shell */}
      <aside className="hidden w-64 flex-col border-r border-border bg-card md:flex">
        <div className="flex h-14 items-center border-b border-border px-4">
          <span className="font-semibold text-card-foreground">Knowledge AI</span>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          <Link
            href="/chat"
            className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
          >
            <MessageCircleIcon className="h-4 w-4" />
            Chat
          </Link>
          <Link
            href="/profile"
            className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
          >
            <UserCircleIcon className="h-4 w-4" />
            Profile
          </Link>

          {user?.role === 'admin' && (
            <>
              <div className="pt-3 pb-1 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Admin
              </div>
              <Link
                href="/admin/sources"
                className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
              >
                <DatabaseIcon className="h-4 w-4" />
                Sources
              </Link>
              <Link
                href="/admin/users"
                className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
              >
                <UsersIcon className="h-4 w-4" />
                Users
              </Link>
              <Link
                href="/admin/connectors"
                className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
              >
                <PlugIcon className="h-4 w-4" />
                Connectors
              </Link>
              <Link
                href="/admin/analytics"
                className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium hover:bg-accent hover:text-accent-foreground"
              >
                <LayoutDashboardIcon className="h-4 w-4" />
                Analytics
              </Link>
            </>
          )}
        </nav>
        <div className="border-t border-border p-4 space-y-2">
          <ThemeToggle />
          <button
            onClick={() => logoutMutation.mutate()}
            disabled={logoutMutation.isPending}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground disabled:opacity-50"
          >
            <LogOutIcon className="h-4 w-4" />
            {logoutMutation.isPending ? 'Logging out…' : 'Log out'}
          </button>
        </div>
      </aside>

      {/* Main content area */}
      <div className="flex flex-1 flex-col">
        <header className="flex h-14 items-center border-b border-border bg-card px-4 md:hidden">
          <span className="font-semibold text-card-foreground">Knowledge AI</span>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </header>
        <main className="flex-1">{children}</main>
      </div>
    </div>
  )
}
