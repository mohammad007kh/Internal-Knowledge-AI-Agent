'use client'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { ChevronRightIcon } from 'lucide-react'
import { usePathname } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
import { SidebarNavLink } from './SidebarNavLink'
import { useSidebar } from './SidebarProvider'
import { type NavItem, isGroupActive } from './nav-config'

/**
 * Collapsible group of navigation items (design doc §8.5).
 *
 * - Clicking the parent toggles child visibility.
 * - When any child is the active route, the group is forced expanded and the
 *   parent label highlights to reflect the active section.
 * - Expanded state persists in localStorage under
 *   `ui:nav-group-<groupKey>`.
 * - In collapsed-sidebar mode the parent renders as a tooltip-only icon and
 *   the children are inlined below it (we don't try to nest popovers in the
 *   already-narrow rail).
 */

export interface SidebarNavGroupProps {
  item: NavItem
  /** Force collapsed/expanded sidebar rendering. */
  collapsed?: boolean
  onNavigate?: () => void
}

const STORAGE_PREFIX = 'ui:nav-group-'

function readStoredExpanded(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  try {
    const value = window.localStorage.getItem(`${STORAGE_PREFIX}${key}`)
    if (value === '1') return true
    if (value === '0') return false
    return fallback
  } catch {
    return fallback
  }
}

function writeStoredExpanded(key: string, value: boolean): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(`${STORAGE_PREFIX}${key}`, value ? '1' : '0')
  } catch {
    // ignore storage failures
  }
}

export function SidebarNavGroup({
  item,
  collapsed: collapsedOverride,
  onNavigate,
}: SidebarNavGroupProps) {
  const pathname = usePathname()
  const { collapsed: ctxCollapsed, isMobile } = useSidebar()
  const collapsed = collapsedOverride ?? (isMobile ? false : ctxCollapsed)
  const groupKey = item.groupKey ?? item.label.toLowerCase()
  const groupActive = isGroupActive(pathname, item)

  // Persisted user preference; child-active state overrides it (forces open).
  const [userExpanded, setUserExpanded] = useState<boolean>(false)

  // Hydrate persisted value after mount. Default to expanded when a child is
  // active so the user lands on the right section without an extra click.
  // We deliberately omit `groupActive` from the deps so route changes don't
  // re-read storage and clobber the user's manual collapse — the
  // `groupActive ||  userExpanded` expression below is the runtime override.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see comment above
  useEffect(() => {
    setUserExpanded(readStoredExpanded(groupKey, groupActive))
  }, [groupKey])

  const expanded = groupActive || userExpanded

  const toggle = useCallback(() => {
    setUserExpanded((prev) => {
      const next = !prev
      writeStoredExpanded(groupKey, next)
      return next
    })
  }, [groupKey])

  const Icon = item.icon
  const children = item.children ?? []

  // --- Collapsed sidebar: tooltip on parent icon, children inlined as icons ---
  if (collapsed) {
    return (
      <div className="space-y-1">
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label={item.label}
              className={cn(
                'mx-auto flex h-9 w-9 items-center justify-center rounded-md transition-colors',
                groupActive
                  ? 'bg-accent text-accent-foreground'
                  : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
              )}
              onClick={toggle}
            >
              <Icon className={cn('h-4 w-4', groupActive && 'text-primary')} aria-hidden />
            </button>
          </TooltipTrigger>
          <TooltipContent side="right">{item.label}</TooltipContent>
        </Tooltip>
        {children.map((child) => (
          <SidebarNavLink
            key={child.href}
            href={child.href}
            label={child.label}
            icon={child.icon}
            collapsed
            onNavigate={onNavigate}
          />
        ))}
      </div>
    )
  }

  // --- Expanded sidebar: real disclosure with chevron ---
  return (
    <div className="space-y-1">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={`nav-group-${groupKey}`}
        onClick={toggle}
        className={cn(
          'flex w-full items-center gap-2.5 rounded-md px-3 py-2.5 text-sm font-medium transition-colors',
          groupActive
            ? 'text-foreground'
            : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
        )}
      >
        <Icon className={cn('h-4 w-4 shrink-0', groupActive && 'text-primary')} aria-hidden />
        <span className="flex-1 truncate text-left">{item.label}</span>
        <ChevronRightIcon
          className={cn(
            'h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform',
            expanded && 'rotate-90'
          )}
          aria-hidden
        />
      </button>
      {expanded ? (
        <div id={`nav-group-${groupKey}`} className="ml-3 space-y-1 border-l border-border/60 pl-2">
          {children.map((child) => (
            <SidebarNavLink
              key={child.href}
              href={child.href}
              label={child.label}
              icon={child.icon}
              onNavigate={onNavigate}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}
