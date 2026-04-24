'use client'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { ThemeToggle } from '@/components/theme-toggle'
import { useAuth } from '@/features/auth/context/AuthContext'
import { useLogout } from '@/features/auth/hooks/useAuthMutations'
import { useNetworkStatus } from '@/hooks/use-network-status'
import { cn } from '@/lib/utils'
import {
  ChevronsUpDownIcon,
  CpuIcon,
  DatabaseIcon,
  LayoutDashboardIcon,
  LogOutIcon,
  MenuIcon,
  MessageCircleIcon,
  PlugIcon,
  ShieldIcon,
  UserCircleIcon,
  UsersIcon,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useState, type ComponentType, type SVGProps } from 'react'

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
  onNavigate?: () => void
}

function NavLink({ href, label, icon: Icon, active, onNavigate }: NavLinkProps) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'relative flex items-center gap-2.5 rounded-md px-3 py-2.5 text-sm font-medium transition-colors',
        active
          ? 'bg-accent text-accent-foreground before:absolute before:left-0 before:top-1/2 before:h-5 before:w-0.5 before:-translate-y-1/2 before:rounded-r-full before:bg-primary'
          : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
      )}
    >
      <Icon className={cn('h-4 w-4', active && 'text-primary')} />
      {label}
    </Link>
  )
}

function isActivePath(pathname: string | null, href: string): boolean {
  if (!pathname) return false
  if (pathname === href) return true
  return pathname.startsWith(`${href}/`)
}

interface SidebarContentProps {
  pathname: string | null
  user: { email?: string | null; full_name?: string | null; role?: string | null } | null
  onLogout: () => void
  isLoggingOut: boolean
  onNavigate?: () => void
}

function SidebarContent({
  pathname,
  user,
  onLogout,
  isLoggingOut,
  onNavigate,
}: SidebarContentProps) {
  const initial = user?.email?.[0]?.toUpperCase() ?? 'U'

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center border-b border-border px-4">
        <span className="font-semibold text-card-foreground">Knowledge AI</span>
      </div>
      <nav className="flex-1 space-y-1 p-3" aria-label="Primary">
        {USER_NAV.map((item) => (
          <NavLink
            key={item.href}
            href={item.href}
            label={item.label}
            icon={item.icon}
            active={isActivePath(pathname, item.href)}
            onNavigate={onNavigate}
          />
        ))}

        {user?.role === 'admin' && (
          <>
            <div className="mt-4 border-t border-border pt-3" aria-hidden />
            <div className="px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Admin
            </div>
            {ADMIN_NAV.map((item) => (
              <NavLink
                key={item.href}
                href={item.href}
                label={item.label}
                icon={item.icon}
                active={isActivePath(pathname, item.href)}
                onNavigate={onNavigate}
              />
            ))}
          </>
        )}
      </nav>

      <div className="border-t border-border p-3 space-y-2">
        <div className="flex items-center justify-between px-1">
          <span className="text-xs text-muted-foreground">Theme</span>
          <ThemeToggle />
        </div>
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-2.5 rounded-md p-2 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Open account menu"
            >
              <span
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
                aria-hidden
              >
                {initial}
              </span>
              <div className="min-w-0 flex-1 text-left">
                <p className="truncate text-sm font-medium">
                  {user?.full_name || user?.email}
                </p>
                <p className="text-xs capitalize text-muted-foreground">
                  {user?.role ?? 'user'}
                </p>
              </div>
              <ChevronsUpDownIcon
                className="h-4 w-4 shrink-0 text-muted-foreground"
                aria-hidden
              />
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" side="top" className="w-56 p-1">
            <Link
              href="/profile"
              onClick={onNavigate}
              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm hover:bg-accent"
            >
              <UserCircleIcon className="h-4 w-4" aria-hidden />
              Profile settings
            </Link>
            <div className="my-1 h-px bg-border" aria-hidden />
            <button
              type="button"
              onClick={onLogout}
              disabled={isLoggingOut}
              className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-destructive hover:bg-destructive/10 disabled:opacity-50"
            >
              <LogOutIcon className="h-4 w-4" aria-hidden />
              {isLoggingOut ? 'Logging out…' : 'Log out'}
            </button>
          </PopoverContent>
        </Popover>
      </div>
    </div>
  )
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const logoutMutation = useLogout()
  const pathname = usePathname()
  const [mobileOpen, setMobileOpen] = useState(false)
  useNetworkStatus()

  const handleLogout = () => logoutMutation.mutate()

  return (
    <div className="flex min-h-screen bg-background">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 flex-col border-r border-border bg-card md:flex">
        <SidebarContent
          pathname={pathname}
          user={user}
          onLogout={handleLogout}
          isLoggingOut={logoutMutation.isPending}
        />
      </aside>

      {/* Main content area */}
      <div className="flex flex-1 flex-col">
        {/* Mobile header */}
        <header className="flex h-14 items-center border-b border-border bg-card px-4 md:hidden">
          <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
            <SheetTrigger asChild>
              <button
                type="button"
                aria-label="Open navigation menu"
                className="-ml-2 inline-flex h-9 w-9 items-center justify-center rounded-md hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <MenuIcon className="h-5 w-5" />
              </button>
            </SheetTrigger>
            <SheetContent side="left" className="w-64 bg-card p-0">
              <SheetTitle className="sr-only">Navigation</SheetTitle>
              <SidebarContent
                pathname={pathname}
                user={user}
                onLogout={handleLogout}
                isLoggingOut={logoutMutation.isPending}
                onNavigate={() => setMobileOpen(false)}
              />
            </SheetContent>
          </Sheet>
          <span className="ml-2 font-semibold text-card-foreground">Knowledge AI</span>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </header>
        <main className="flex-1">{children}</main>
      </div>
    </div>
  )
}
