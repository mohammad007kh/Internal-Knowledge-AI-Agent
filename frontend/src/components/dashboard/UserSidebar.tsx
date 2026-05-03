'use client'

import { ChatSidebarGroup } from '@/components/chat/ChatSidebarGroup'
import type { ReactNode } from 'react'
import { AdminPanelButton } from './AdminPanelButton'
import { MobileHeader, Sidebar } from './Sidebar'
import { SidebarNavGroup } from './SidebarNavGroup'
import { SidebarNavLink } from './SidebarNavLink'
import { ThemeToggleRow } from './ThemeToggleRow'
import { UserPopover } from './UserPopover'
import { USER_NAV } from './nav-config'

const BRAND = 'Knowledge AI'

function renderUserNav(onNavigate?: () => void): ReactNode {
  return (
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
}

function renderUserFooter(onNavigate?: () => void): ReactNode {
  return (
    <>
      <AdminPanelButton onNavigate={onNavigate} />
      <ThemeToggleRow />
      <UserPopover onNavigate={onNavigate} />
    </>
  )
}

/**
 * Desktop-only sidebar `<aside>` for the user shell.
 *
 * The mobile header is rendered separately by `<UserMobileHeader>` so the
 * layout can place it ABOVE the flex row (instead of as a sibling of
 * `<main>`, which previously made it sit side-by-side with content on narrow
 * viewports below the `md` breakpoint).
 *
 * Both components consume the shared `SelectedSessionProvider` mounted by the
 * `(user)/layout.tsx` so the inline chat history sheet and the chat surface
 * see the same active session.
 */
export function UserSidebar() {
  return <Sidebar brand={BRAND} nav={renderUserNav} footer={renderUserFooter} />
}

/**
 * Mobile-only top header for the user shell. Renders the hamburger trigger
 * and theme toggle; the slide-out sheet contains the same nav and footer as
 * the desktop sidebar.
 */
export function UserMobileHeader() {
  return <MobileHeader brand={BRAND} nav={renderUserNav} footer={renderUserFooter} />
}
