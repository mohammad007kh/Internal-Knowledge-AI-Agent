'use client'

import { ThemeToggle } from '@/components/theme-toggle'
import { useAuth } from '@/features/auth/context/AuthContext'
import { useLogout } from '@/features/auth/hooks/useAuthMutations'
import { useNetworkStatus } from '@/hooks/use-network-status'
import { cn } from '@/lib/utils'
import {
  CpuIcon,
  DatabaseIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  MessageCircleIcon,
  PlugIcon,
  ShieldIcon,
  UserCircleIcon,
  UsersIcon,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import type { ComponentType, SVGProps } from 'react'

type IconType = ComponentType<SVGProps<SVGSVGElement> & { className?: string }>

interface NavItem {
  href: string
  label: string
  icon: IconType
}

const USER_NAV: NavItem[] = [
  { href: '/chat', label: 'Chat', icon: MessageCircleIcon },
  { href: '/profile', label: 'Profile', icon: UserCircleIcon },
]

const ADMIN_NAV: NavItem[] = [
  { href: '/admin/sources', label: 'Sources', icon: DatabaseIcon },
  { href: '/admin/users', label: 'Users', icon: UsersIcon },
  { href: '/admin/connectors', label: 'Connectors', icon: PlugIcon },
  { href: '/admin/analytics', label: 'Analytics', icon: LayoutDashboardIcon },
  { href: '/admin/llm-settings', label: 'LLM Settings', icon: CpuIcon },
  { href: '/admin/policy', label: 'Policy', icon: ShieldIcon },
]

interface NavLinkProps {
  href: string
  label: string
  icon: IconType
  active: boolean
}

function NavLink({ href, label, icon: Icon, active }: NavLinkProps) {
  return (
    <Link
      href={href}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors',
        active
          ? 'bg-accent text-accent-foreground'
          : 'hover:bg-accent hover:text-accent-foreground'
      )}
    >
      <Icon className="h-4 w-4" />
      {label}
    </Link>
  )
}

function isActivePath(pathname: string | null, href: string): boolean {
  if (!pathname) return false
  if (pathname === href) return true
  return pathname.startsWith(`${href}/`)
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const logoutMutation = useLogout()
  const pathname = usePathname()
  useNetworkStatus()

  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar shell */}
      <aside className="hidden w-64 flex-col border-r border-border bg-card md:flex">
        <div className="flex h-14 items-center border-b border-border px-4">
          <span className="font-semibold text-card-foreground">Knowledge AI</span>
        </div>
        <nav className="flex-1 p-4 space-y-1" aria-label="Primary">
          {USER_NAV.map((item) => (
            <NavLink
              key={item.href}
              href={item.href}
              label={item.label}
              icon={item.icon}
              active={isActivePath(pathname, item.href)}
            />
          ))}

          {user?.role === 'admin' && (
            <>
              <div className="pt-3 pb-1 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Admin
              </div>
              {ADMIN_NAV.map((item) => (
                <NavLink
                  key={item.href}
                  href={item.href}
                  label={item.label}
                  icon={item.icon}
                  active={isActivePath(pathname, item.href)}
                />
              ))}
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
