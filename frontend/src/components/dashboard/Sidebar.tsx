'use client'

import { ThemeToggle } from '@/components/theme-toggle'
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { TooltipProvider } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { MenuIcon, XIcon } from 'lucide-react'
import Link from 'next/link'
import type { ReactNode } from 'react'
import { useSidebar } from './SidebarProvider'
import { SidebarToggleButton } from './SidebarToggleButton'

export interface SidebarProps {
  /** Brand label rendered in the header (e.g. "Knowledge AI"). */
  brand: string
  /** Optional accent label rendered after brand (e.g. "Admin"). */
  brandSuffix?: string
  /** Sidebar nav. Receives `onNavigate` from the mobile sheet to auto-close it. */
  nav: (onNavigate?: () => void) => ReactNode
  /** Footer content (theme toggle, user popover, etc.). */
  footer: (onNavigate?: () => void) => ReactNode
  /** Aria label for the navigation region. */
  ariaLabel?: string
}

/**
 * Desktop sidebar `<aside>`.
 *
 * Width transitions: `w-60` expanded ↔ `w-14` collapsed.
 * Hidden below the `md` breakpoint — use `<MobileHeader>` for mobile.
 */
export function Sidebar({ brand, brandSuffix, nav, footer, ariaLabel = 'Primary' }: SidebarProps) {
  const { collapsed } = useSidebar()

  const header = (
    <div
      className={cn(
        'flex h-14 items-center border-b border-border',
        collapsed ? 'justify-center px-2' : 'justify-between px-3'
      )}
    >
      {collapsed ? (
        <Link
          href="/chat"
          aria-label={brand}
          className="flex h-8 w-8 items-center justify-center rounded-md bg-primary/10 text-sm font-semibold text-primary hover:bg-primary/15"
        >
          {brand.charAt(0)}
        </Link>
      ) : (
        <Link
          href="/chat"
          className="flex min-w-0 items-baseline gap-1.5 text-sm font-semibold text-card-foreground"
        >
          <span className="truncate">{brand}</span>
          {brandSuffix ? (
            <span className="truncate text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {brandSuffix}
            </span>
          ) : null}
        </Link>
      )}
      <SidebarToggleButton />
    </div>
  )

  return (
    <TooltipProvider delayDuration={0}>
      <aside
        aria-label={ariaLabel}
        className={cn(
          'hidden flex-col border-r border-border bg-card transition-[width] duration-200 ease-out md:flex md:sticky md:top-0 md:h-screen',
          collapsed ? 'w-14' : 'w-60'
        )}
      >
        {header}
        <nav
          aria-label={ariaLabel}
          className={cn('flex-1 space-y-1 overflow-y-auto py-3', collapsed ? 'px-1.5' : 'px-3')}
        >
          {nav()}
        </nav>
        <div className={cn('border-t border-border space-y-2', collapsed ? 'p-2' : 'p-3')}>
          {footer()}
        </div>
      </aside>
    </TooltipProvider>
  )
}

export interface MobileHeaderProps {
  brand: string
  brandSuffix?: string
  nav: (onNavigate?: () => void) => ReactNode
  footer: (onNavigate?: () => void) => ReactNode
  ariaLabel?: string
}

/**
 * Mobile-only header with a hamburger button that opens a `<Sheet>` containing
 * the same nav + footer. Always renders nav in expanded mode (no collapse).
 */
export function MobileHeader({
  brand,
  brandSuffix,
  nav,
  footer,
  ariaLabel = 'Primary',
}: MobileHeaderProps) {
  const { mobileOpen, setMobileOpen } = useSidebar()
  const closeMobile = () => setMobileOpen(false)

  return (
    <TooltipProvider delayDuration={0}>
      <header className="sticky top-0 z-30 flex h-14 items-center border-b border-border bg-card px-4 md:hidden">
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
          <SheetContent side="left" className="w-72 max-w-[80vw] bg-card p-0">
            <SheetTitle className="sr-only">{brand} navigation</SheetTitle>
            <SheetDescription className="sr-only">
              Primary navigation links for {brand}.
            </SheetDescription>
            <SheetClose
              aria-label="Close navigation"
              className="absolute right-3 top-3 z-10 inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <XIcon className="h-5 w-5" aria-hidden />
            </SheetClose>
            <div className="flex h-full flex-col">
              <div className="flex h-14 items-center border-b border-border px-4">
                <span className="font-semibold text-card-foreground">{brand}</span>
                {brandSuffix ? (
                  <span className="ml-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                    {brandSuffix}
                  </span>
                ) : null}
              </div>
              <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-3" aria-label={ariaLabel}>
                {nav(closeMobile)}
              </nav>
              <div className="border-t border-border p-3 space-y-2">{footer(closeMobile)}</div>
            </div>
          </SheetContent>
        </Sheet>
        <Link
          href="/chat"
          className="ml-2 flex items-baseline gap-1.5 font-semibold text-card-foreground"
        >
          <span>{brand}</span>
          {brandSuffix ? (
            <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              {brandSuffix}
            </span>
          ) : null}
        </Link>
        <div className="ml-auto">
          <ThemeToggle />
        </div>
      </header>
    </TooltipProvider>
  )
}
