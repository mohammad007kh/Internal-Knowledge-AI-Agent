'use client'

import { SelectedSessionProvider } from '@/components/chat/SelectedSessionContext'
import { SidebarProvider } from '@/components/dashboard/SidebarProvider'
import { UserMobileHeader, UserSidebar } from '@/components/dashboard/UserSidebar'
import { useNetworkStatus } from '@/hooks/use-network-status'

/**
 * User shell layout.
 *
 * Layout structure:
 *
 *   <column>
 *     <UserMobileHeader />         (mobile-only top bar; hidden md+)
 *     <row>
 *       <UserSidebar />            (desktop-only aside; hidden under md)
 *       <main />                   (always full remaining width)
 *     </row>
 *   </column>
 *
 * The mobile header is intentionally a sibling of the row — NOT a sibling of
 * `<main>` — so it never competes for horizontal space with page content on
 * narrow viewports. Previously the header sat inside the row and ate ~25% of
 * the viewport width below the `md` breakpoint, squeezing main content into
 * a useless narrow column.
 *
 * `SelectedSessionProvider` is hoisted here (above both header and main) so
 * the inline chat history sheet inside the mobile header reads/writes the
 * same active session as the chat surface. Mounting it inside the sidebar
 * components individually would split the state across two contexts.
 */
export default function UserLayout({ children }: { children: React.ReactNode }) {
  useNetworkStatus()

  return (
    <SidebarProvider>
      <SelectedSessionProvider>
        <div className="flex min-h-screen flex-col bg-background">
          <UserMobileHeader />
          <div className="flex min-h-0 flex-1">
            <UserSidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <main className="flex-1">{children}</main>
            </div>
          </div>
        </div>
      </SelectedSessionProvider>
    </SidebarProvider>
  )
}
