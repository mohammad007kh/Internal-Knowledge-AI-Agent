'use client'

import { BackToAppLink } from './BackToAppLink'
import { MobileHeader, Sidebar } from './Sidebar'
import { SidebarNavGroup } from './SidebarNavGroup'
import { SidebarNavLink } from './SidebarNavLink'
import { ThemeToggleRow } from './ThemeToggleRow'
import { UserPopover } from './UserPopover'
import { ADMIN_NAV } from './nav-config'

const BRAND = 'Knowledge AI'
const BRAND_SUFFIX = 'Admin'

export function AdminSidebar() {
  const renderNav = (onNavigate?: () => void) => (
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

  const renderFooter = (onNavigate?: () => void) => (
    <>
      <ThemeToggleRow />
      <UserPopover onNavigate={onNavigate} />
    </>
  )

  return (
    <>
      <Sidebar
        brand={BRAND}
        brandSuffix={BRAND_SUFFIX}
        nav={renderNav}
        footer={renderFooter}
        ariaLabel="Admin"
      />
      <MobileHeader
        brand={BRAND}
        brandSuffix={BRAND_SUFFIX}
        nav={renderNav}
        footer={renderFooter}
        ariaLabel="Admin"
      />
    </>
  )
}
