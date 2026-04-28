'use client'

import { ChatSidebarGroup } from '@/components/chat/ChatSidebarGroup'
import { SelectedSessionProvider } from '@/components/chat/SelectedSessionContext'
import { AdminPanelButton } from './AdminPanelButton'
import { MobileHeader, Sidebar } from './Sidebar'
import { SidebarNavGroup } from './SidebarNavGroup'
import { SidebarNavLink } from './SidebarNavLink'
import { ThemeToggleRow } from './ThemeToggleRow'
import { UserPopover } from './UserPopover'
import { USER_NAV } from './nav-config'

const BRAND = 'Knowledge AI'

export function UserSidebar() {
  const renderNav = (onNavigate?: () => void) => (
    <>
      {USER_NAV.map((item) => {
        // The "Chat" entry is owned by ChatSidebarGroup which renders inline
        // recent sessions, a "+ New chat" button, and an "All chats" sheet
        // trigger. Keeps a single 2-pane shell across the whole user app.
        if (item.href === '/chat') {
          return <ChatSidebarGroup key={item.href} onNavigate={onNavigate} />
        }
        if (item.children && item.children.length > 0) {
          return <SidebarNavGroup key={item.href} item={item} onNavigate={onNavigate} />
        }
        return (
          <SidebarNavLink
            key={item.href}
            href={item.href}
            label={item.label}
            icon={item.icon}
            onNavigate={onNavigate}
          />
        )
      })}
    </>
  )

  const renderFooter = (onNavigate?: () => void) => (
    <>
      <AdminPanelButton onNavigate={onNavigate} />
      <ThemeToggleRow />
      <UserPopover onNavigate={onNavigate} />
    </>
  )

  // SelectedSessionProvider must wrap the sidebar because the inline chat
  // history group (and its keyboard shortcut) reads/writes the active session
  // from anywhere in the user shell — not just under `/chat`.
  return (
    <SelectedSessionProvider>
      <Sidebar brand={BRAND} nav={renderNav} footer={renderFooter} />
      <MobileHeader brand={BRAND} nav={renderNav} footer={renderFooter} />
    </SelectedSessionProvider>
  )
}
