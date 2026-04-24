'use client'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useAuth } from '@/features/auth/context/AuthContext'
import { cn } from '@/lib/utils'
import { ShieldIcon } from 'lucide-react'
import Link from 'next/link'
import { useSidebar } from './SidebarProvider'

export interface AdminPanelButtonProps {
  onNavigate?: () => void
}

/**
 * Renders a "Admin Panel" entry in the user shell footer. Only visible to
 * authenticated admins — non-admins (and unauthenticated users) see nothing.
 */
export function AdminPanelButton({ onNavigate }: AdminPanelButtonProps) {
  const { user } = useAuth()
  const { collapsed, isMobile } = useSidebar()

  if (user?.role !== 'admin') return null

  const isCollapsed = !isMobile && collapsed

  if (isCollapsed) {
    return (
      <Tooltip delayDuration={0}>
        <TooltipTrigger asChild>
          <Link
            href="/admin"
            onClick={onNavigate}
            aria-label="Admin panel"
            className={cn(
              'mx-auto flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground'
            )}
          >
            <ShieldIcon className="h-4 w-4" aria-hidden />
          </Link>
        </TooltipTrigger>
        <TooltipContent side="right">Admin Panel</TooltipContent>
      </Tooltip>
    )
  }

  return (
    <Link
      href="/admin"
      onClick={onNavigate}
      className={cn(
        'flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground'
      )}
    >
      <ShieldIcon className="h-4 w-4 shrink-0" aria-hidden />
      <span className="truncate">Admin Panel</span>
    </Link>
  )
}
