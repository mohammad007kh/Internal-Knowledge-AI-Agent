'use client'

import { SidebarProvider } from '@/components/dashboard/SidebarProvider'
import { UserSidebar } from '@/components/dashboard/UserSidebar'
import { useNetworkStatus } from '@/hooks/use-network-status'

export default function UserLayout({ children }: { children: React.ReactNode }) {
  useNetworkStatus()

  return (
    <SidebarProvider>
      <div className="flex min-h-screen bg-background">
        <UserSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <main className="flex-1">{children}</main>
        </div>
      </div>
    </SidebarProvider>
  )
}
