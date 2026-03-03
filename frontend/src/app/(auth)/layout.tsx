import type { ReactNode } from 'react'

import { ThemeToggle } from '@/components/theme-toggle'

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      {/* Theme toggle pinned to top-right corner */}
      <div className="fixed top-4 right-4">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            Internal Knowledge AI
          </h1>
        </div>
        {children}
      </div>
    </div>
  )
}
