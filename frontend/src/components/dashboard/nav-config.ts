import {
  CpuIcon,
  DatabaseIcon,
  Layers,
  LayoutDashboardIcon,
  MessageCircleIcon,
  ScrollTextIcon,
  ShieldIcon,
  SlidersHorizontalIcon,
  SparklesIcon,
  UsersIcon,
} from 'lucide-react'
import type { ComponentType, SVGProps } from 'react'

export type IconType = ComponentType<SVGProps<SVGSVGElement> & { className?: string }>

/**
 * Top-level / nested navigation entry.
 *
 * Items with `children` render as a collapsible group (no `href` of their own
 * is followed; clicking the parent toggles its children's visibility).
 * `groupKey` identifies the parent for localStorage-backed expansion state.
 */
export interface NavItem {
  href: string
  label: string
  icon: IconType
  /** When provided, the entry renders as a collapsible group. */
  children?: readonly NavItem[]
  /** Stable key used to persist expanded state for groups. */
  groupKey?: string
}

/**
 * Top-level navigation for the user shell.
 *
 * Note: Profile is intentionally NOT listed here. It is reachable via the
 * "Profile settings" entry inside the user popover at the bottom of the
 * sidebar (see `UserPopover.tsx`), which is the canonical location.
 */
export const USER_NAV: readonly NavItem[] = [
  { href: '/chat', label: 'Chat', icon: MessageCircleIcon },
] as const

/**
 * Top-level navigation for the admin shell.
 *
 * AI Models / Embedders / LLM Settings sit under a collapsible "AI" group
 * per design doc §8.5.
 */
export const ADMIN_NAV: readonly NavItem[] = [
  { href: '/admin/sources', label: 'Sources', icon: DatabaseIcon },
  { href: '/admin/users', label: 'Users', icon: UsersIcon },
  { href: '/admin/analytics', label: 'Analytics', icon: LayoutDashboardIcon },
  {
    href: '/admin/ai',
    label: 'AI',
    icon: SparklesIcon,
    groupKey: 'ai',
    children: [
      { href: '/admin/ai-models', label: 'AI Models', icon: CpuIcon },
      { href: '/admin/embedders', label: 'Embedders', icon: Layers },
      { href: '/admin/llm-settings', label: 'LLM Settings', icon: SlidersHorizontalIcon },
    ],
  },
  { href: '/admin/policy', label: 'Policy', icon: ShieldIcon },
  { href: '/admin/audit-log', label: 'Audit log', icon: ScrollTextIcon },
] as const

/**
 * Returns true when `pathname` matches `href` exactly or is a descendant route.
 */
export function isActivePath(pathname: string | null, href: string): boolean {
  if (!pathname) return false
  if (pathname === href) return true
  return pathname.startsWith(`${href}/`)
}

/**
 * Returns true when any child of a group is active for the given `pathname`.
 */
export function isGroupActive(pathname: string | null, item: NavItem): boolean {
  if (!item.children || item.children.length === 0) return false
  return item.children.some((child) => isActivePath(pathname, child.href))
}
