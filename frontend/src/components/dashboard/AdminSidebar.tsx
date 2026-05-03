'use client'

import type { ReactNode } from 'react'
import { BackToAppLink } from './BackToAppLink'
import { MobileHeader, Sidebar } from './Sidebar'
import { SidebarNavGroup } from './SidebarNavGroup'
import { SidebarNavLink } from './SidebarNavLink'
import { ThemeToggleRow } from './ThemeToggleRow'
import { UserPopover } from './UserPopover'
import { ADMIN_NAV } from './nav-config'

const BRAND = 'Knowledge AI'
const BRAND_SUFFIX = 'Admin'

function renderAdminNav(onNavigate?: () => void): ReactNode {
  return (
    <>
      <BackToAppLink onNavigate={onNavigate} />
      <div className="my-2 border-t border-border" aria-hidden />
      {ADMIN_NAV.map((item) =>
        item.children && item.children.length > 0 ? (
          <SidebarNavGroup key={item.href} item={item} onNavigate={onNavigate} />
        ) : (
          <SidebarNavLink
            key={item.href}
            href={item.href}
            label={item.label}
            icon={item.icon}
            onNavigate={onNavigate}
          />
        )
      )}
    </>
  )
}

function renderAdminFooter(onNavigate?: () => void): ReactNode {
  return (
    <>
      <ThemeToggleRow />
      <UserPopover onNavigate={onNavigate} />
    </>
  )
}

/**
 * Desktop-only sidebar `<aside>` for the admin shell.
 *
 * The mobile header is rendered separately by `<AdminMobileHeader>` so the
 * layout can stack it ABOVE the flex row on narrow viewports. Rendering the
 * mobile header as a flex sibling of `<main>` (the previous structure) made
 * it occupy a fixed slice of horizontal space and squeezed page content into
 * a useless narrow column below the `md` breakpoint.
 */
export function AdminSidebar() {
  return (
    <Sidebar
      brand={BRAND}
      brandSuffix={BRAND_SUFFIX}
      nav={renderAdminNav}
      footer={renderAdminFooter}
      ariaLabel="Admin"
    />
  )
}

/**
 * Mobile-only top header for the admin shell. Hamburger opens a `<Sheet>`
 * that mirrors the desktop sidebar nav.
 */
export function AdminMobileHeader() {
  return (
    <MobileHeader
      brand={BRAND}
      brandSuffix={BRAND_SUFFIX}
      nav={renderAdminNav}
      footer={renderAdminFooter}
      ariaLabel="Admin"
    />
  )
}
