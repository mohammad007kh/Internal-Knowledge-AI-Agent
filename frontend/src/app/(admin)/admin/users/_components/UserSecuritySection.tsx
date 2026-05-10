'use client'

import { Button } from '@/components/ui/button'
import { apiClient } from '@/lib/api-client'
import { useMutation } from '@tanstack/react-query'
import { KeyRoundIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

/**
 * UserSecuritySection
 * ------------------------------------------------------------
 * Admin-triggered password reset. Tracks "Last sent" locally
 * (server doesn't expose this on /users/{id}) — gives the admin
 * just enough feedback to avoid double-sending.
 */

interface UserSecuritySectionProps {
  userId: string
}

function formatRelative(iso: string | null): string {
  if (!iso) return 'never'
  const sentAt = new Date(iso)
  if (Number.isNaN(sentAt.getTime())) return 'never'
  const deltaMs = Date.now() - sentAt.getTime()
  const min = Math.round(deltaMs / 60000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  const days = Math.round(hr / 24)
  return `${days}d ago`
}

export function UserSecuritySection({ userId }: UserSecuritySectionProps) {
  const [lastSentAt, setLastSentAt] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () => apiClient.post(`/api/v1/users/${userId}/reset-password`),
    onSuccess: () => {
      const ts = new Date().toISOString()
      setLastSentAt(ts)
      toast.success('Password reset email sent.')
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : 'Failed to send reset email'
      toast.error(message)
    },
  })

  return (
    <section aria-label="Security" className="space-y-1">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Security
      </h3>
      <div className="space-y-2 rounded-md border bg-card/40 p-3">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => mutation.mutate()}
          disabled={mutation.isPending}
          className="gap-1.5"
        >
          <KeyRoundIcon className="h-3.5 w-3.5" aria-hidden />
          {mutation.isPending ? 'Sending…' : 'Send password reset email'}
        </Button>
        <p className="text-xs text-muted-foreground">Last sent: {formatRelative(lastSentAt)}</p>
      </div>
    </section>
  )
}
