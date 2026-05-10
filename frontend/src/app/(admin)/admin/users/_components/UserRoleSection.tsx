'use client'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { usersKeys } from '@/features/users/hooks/useUsersQueries'
import { apiClient } from '@/lib/api-client'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useId, useState } from 'react'
import { toast } from 'sonner'

/**
 * UserRoleSection
 * ------------------------------------------------------------
 * Role gets its own row + dedicated [Save] button because role
 * changes are auditable security events. Hits PATCH /role
 * (separate endpoint from the profile patch).
 */

interface UserRoleSectionProps {
  userId: string
  currentRole: 'admin' | 'user'
}

const ROLE_DESCRIPTIONS: Record<'admin' | 'user', string> = {
  admin: 'Admins manage sources and users.',
  user: 'Members can ask questions and read sources.',
}

export function UserRoleSection({ userId, currentRole }: UserRoleSectionProps) {
  const queryClient = useQueryClient()
  const [draftRole, setDraftRole] = useState<'admin' | 'user'>(currentRole)
  const fieldId = useId()

  // Sync local state if the upstream query refreshes (e.g. after another tab
  // changes the role).
  useEffect(() => {
    setDraftRole(currentRole)
  }, [currentRole])

  const mutation = useMutation({
    mutationFn: (role: 'admin' | 'user') =>
      apiClient.patch(`/api/v1/users/${userId}/role`, { role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
      toast.success('Role updated.')
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : 'Failed to update role'
      toast.error(message)
      setDraftRole(currentRole)
    },
  })

  const dirty = draftRole !== currentRole

  return (
    <section aria-label="Role and access" className="space-y-1">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Role &amp; access
      </h3>
      <div className="rounded-md border bg-card/40 p-3">
        <div className="grid grid-cols-[120px_1fr_auto] items-center gap-2 sm:grid-cols-[140px_1fr_auto]">
          <Label htmlFor={fieldId} className="text-xs text-muted-foreground">
            Role
          </Label>
          <Select
            value={draftRole}
            onValueChange={(v) => setDraftRole(v as 'admin' | 'user')}
          >
            <SelectTrigger id={fieldId} className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="user">Member</SelectItem>
              <SelectItem value="admin">Admin</SelectItem>
            </SelectContent>
          </Select>
          <Button
            type="button"
            size="sm"
            variant={dirty ? 'default' : 'ghost'}
            disabled={!dirty || mutation.isPending}
            onClick={() => mutation.mutate(draftRole)}
            aria-label="Save role"
          >
            {mutation.isPending ? 'Saving…' : 'Save'}
          </Button>
        </div>
        <p className="mt-2 pl-0 text-xs text-muted-foreground sm:pl-[140px]">
          {ROLE_DESCRIPTIONS[draftRole]}
        </p>
      </div>
    </section>
  )
}
