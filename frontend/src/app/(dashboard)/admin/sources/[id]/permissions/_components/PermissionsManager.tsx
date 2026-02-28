'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  useGrantPermission,
  useRevokePermission,
  useSourcePermissions,
} from '@/features/source-permissions/hooks/useSourcePermissions'
import { UserMinus, UserPlus } from 'lucide-react'
import { useState } from 'react'

interface PermissionsManagerProps {
  sourceId: string
}

export function PermissionsManager({ sourceId }: PermissionsManagerProps) {
  const [newUserId, setNewUserId] = useState('')
  const { data: userIds = [], isLoading } = useSourcePermissions(sourceId)
  const grantMutation = useGrantPermission(sourceId)
  const revokeMutation = useRevokePermission(sourceId)

  function handleGrant() {
    const trimmed = newUserId.trim()
    if (!trimmed) return
    grantMutation.mutate(trimmed, {
      onSuccess: () => setNewUserId(''),
    })
  }

  if (isLoading) {
    return <div className="py-4 text-center text-muted-foreground">Loading permissions…</div>
  }

  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        <Input
          placeholder="User UUID"
          value={newUserId}
          onChange={(e) => setNewUserId(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleGrant()
          }}
          className="max-w-sm"
        />
        <Button onClick={handleGrant} disabled={!newUserId.trim() || grantMutation.isPending}>
          <UserPlus className="mr-2 h-4 w-4" />
          Grant
        </Button>
      </div>

      {userIds.length === 0 ? (
        <p className="text-sm text-muted-foreground">No users have access to this source yet.</p>
      ) : (
        <ul className="space-y-2">
          {userIds.map((userId) => (
            <li
              key={userId}
              className="flex items-center justify-between rounded-md border px-4 py-2"
            >
              <span className="font-mono text-sm">{userId}</span>
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:text-destructive"
                onClick={() => revokeMutation.mutate(userId)}
                disabled={revokeMutation.isPending}
              >
                <UserMinus className="mr-1 h-4 w-4" />
                Revoke
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
