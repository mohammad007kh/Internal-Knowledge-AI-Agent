'use client'

import { AdminSidebar } from '@/components/dashboard/AdminSidebar'
import { SidebarProvider } from '@/components/dashboard/SidebarProvider'
import { useAuth } from '@/features/auth/context/AuthContext'
import { useNetworkStatus } from '@/hooks/use-network-status'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  const router = useRouter()
  useNetworkStatus()

  // AuthZ guard — redirect non-admins to /chat. Backend also enforces this on
  // every admin endpoint via require_admin; this is a UX safeguard only.
  useEffect(() => {
    if (!isLoading && (!user || user.role !== 'admin')) {
      router.replace('/chat')
    }
  }, [user, isLoading, router])

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <span className="text-muted-foreground text-sm">Loading…</span>
      </div>
    )
  }

  if (!user || user.role !== 'admin') {
    return null
  }

  return (
    <SidebarProvider>
      <div className="flex min-h-screen bg-background">
        <AdminSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <main className="flex-1">{children}</main>
        </div>
      </div>
    </SidebarProvider>
  )
}
