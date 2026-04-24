import {
  CpuIcon,
  DatabaseIcon,
  LayoutDashboardIcon,
  MessageCircleIcon,
  PlugIcon,
  ShieldIcon,
  UserCircleIcon,
  UsersIcon,
} from 'lucide-react'
import type { ComponentType, SVGProps } from 'react'

export type IconType = ComponentType<SVGProps<SVGSVGElement> & { className?: string }>

export interface NavItem {
  href: string
  label: string
  icon: IconType
}

/** Top-level navigation for the user shell. */
export const USER_NAV: readonly NavItem[] = [
  { href: '/chat', label: 'Chat', icon: MessageCircleIcon },
  { href: '/profile', label: 'Profile', icon: UserCircleIcon },
] as const

/** Top-level navigation for the admin shell. */
export const ADMIN_NAV: readonly NavItem[] = [
  { href: '/admin/sources', label: 'Sources', icon: DatabaseIcon },
  { href: '/admin/users', label: 'Users', icon: UsersIcon },
  { href: '/admin/connectors', label: 'Connectors', icon: PlugIcon },
  { href: '/admin/analytics', label: 'Analytics', icon: LayoutDashboardIcon },
  { href: '/admin/llm-settings', label: 'LLM Settings', icon: CpuIcon },
  { href: '/admin/policy', label: 'Policy', icon: ShieldIcon },
] as const

/**
 * Returns true when `pathname` matches `href` exactly or is a descendant route.
 */
export function isActivePath(pathname: string | null, href: string): boolean {
  if (!pathname) return false
  if (pathname === href) return true
  return pathname.startsWith(`${href}/`)
}
