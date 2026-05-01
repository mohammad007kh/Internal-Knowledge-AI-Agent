'use client'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { ArrowLeftIcon } from 'lucide-react'
import Link from 'next/link'
import { useSidebar } from './SidebarProvider'

export interface BackToAppLinkProps {
  onNavigate?: () => void
}

/** Sits at the top of the admin sidebar to return the user to the chat surface. */
export function BackToAppLink({ onNavigate }: BackToAppLinkProps) {
  const { collapsed, isMobile } = useSidebar()
  const isCollapsed = !isMobile && collapsed

  if (isCollapsed) {
    return (
      <Tooltip delayDuration={0}>
        <TooltipTrigger asChild>
          <Link
            href="/chat"
            onClick={onNavigate}
            aria-label="Back to app"
            className={cn(
              'mx-auto flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent hover:text-foreground'
            )}
          >
            <ArrowLeftIcon className="h-4 w-4" aria-hidden />
          </Link>
        </TooltipTrigger>
        <TooltipContent side="right">Back to App</TooltipContent>
      </Tooltip>
    )
  }

  return (
    <Link
      href="/chat"
      onClick={onNavigate}
      className={cn(
        'flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground'
      )}
    >
      <ArrowLeftIcon className="h-4 w-4 shrink-0" aria-hidden />
      <span className="truncate">Back to App</span>
    </Link>
  )
}
