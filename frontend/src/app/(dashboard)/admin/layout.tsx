'use client'

import { useAuth } from '@/features/auth/context/AuthContext'
import { useRouter } from 'next/navigation'
import { useEffect } from 'react'

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  const router = useRouter()

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

  return <>{children}</>
}
