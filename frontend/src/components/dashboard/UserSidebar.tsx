'use client'

import { AdminPanelButton } from './AdminPanelButton'
import { MobileHeader, Sidebar } from './Sidebar'
import { SidebarNavLink } from './SidebarNavLink'
import { ThemeToggleRow } from './ThemeToggleRow'
import { UserPopover } from './UserPopover'
import { USER_NAV } from './nav-config'

const BRAND = 'Knowledge AI'

export function UserSidebar() {
  const renderNav = (onNavigate?: () => void) => (
    <>
      {USER_NAV.map((item) => (
        <SidebarNavLink
          key={item.href}
          href={item.href}
          label={item.label}
          icon={item.icon}
          onNavigate={onNavigate}
        />
      ))}
    </>
  )

  const renderFooter = (onNavigate?: () => void) => (
    <>
      <AdminPanelButton onNavigate={onNavigate} />
      <ThemeToggleRow />
      <UserPopover onNavigate={onNavigate} />
    </>
  )

  return (
    <>
      <Sidebar brand={BRAND} nav={renderNav} footer={renderFooter} />
      <MobileHeader brand={BRAND} nav={renderNav} footer={renderFooter} />
    </>
  )
}
