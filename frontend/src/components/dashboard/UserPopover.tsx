'use client'

import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useAuth } from '@/features/auth/context/AuthContext'
import { useLogout } from '@/features/auth/hooks/useAuthMutations'
import { cn } from '@/lib/utils'
import { ChevronsUpDownIcon, LogOutIcon, UserCircleIcon } from 'lucide-react'
import Link from 'next/link'
import { useSidebar } from './SidebarProvider'

export interface UserPopoverProps {
  /** Optional callback fired when a popover link is clicked (e.g. close mobile sheet). */
  onNavigate?: () => void
}

export function UserPopover({ onNavigate }: UserPopoverProps) {
  const { user } = useAuth()
  const logoutMutation = useLogout()
  const { collapsed, isMobile } = useSidebar()
  const isCollapsed = !isMobile && collapsed

  const initial = user?.email?.[0]?.toUpperCase() ?? 'U'
  const displayName = user?.full_name || user?.email || 'Account'
  const role = user?.role ?? 'user'

  const handleLogout = () => logoutMutation.mutate()

  const avatar = (
    <span
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary"
      aria-hidden
    >
      {initial}
    </span>
  )

  const trigger = isCollapsed ? (
    <button
      type="button"
      className="mx-auto flex h-9 w-9 items-center justify-center rounded-md hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      aria-label={`Open account menu for ${displayName}`}
    >
      {avatar}
    </button>
  ) : (
    <button
      type="button"
      className={cn(
        'flex w-full items-center gap-2.5 rounded-md p-2 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'
      )}
      aria-label="Open account menu"
    >
      {avatar}
      <div className="min-w-0 flex-1 text-left">
        <p className="truncate text-sm font-medium">{displayName}</p>
        <p className="text-xs capitalize text-muted-foreground">{role}</p>
      </div>
      <ChevronsUpDownIcon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
    </button>
  )

  const popoverContent = (
    <PopoverContent align={isCollapsed ? 'start' : 'end'} side="top" className="w-56 p-1">
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
        onClick={handleLogout}
        disabled={logoutMutation.isPending}
        className="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-destructive hover:bg-destructive/10 disabled:opacity-50"
      >
        <LogOutIcon className="h-4 w-4" aria-hidden />
        {logoutMutation.isPending ? 'Logging out…' : 'Log out'}
      </button>
    </PopoverContent>
  )

  if (isCollapsed) {
    return (
      <Popover>
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>{trigger}</PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent side="right">{displayName}</TooltipContent>
        </Tooltip>
        {popoverContent}
      </Popover>
    )
  }

  return (
    <Popover>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      {popoverContent}
    </Popover>
  )
}
