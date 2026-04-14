'use client'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  useGrantPermission,
  useRevokePermission,
  useSourcePermissions,
} from '@/features/source-permissions/hooks/useSourcePermissions'
import { apiClient } from '@/lib/api-client'
import { UserMinus, UserPlus } from 'lucide-react'
import { useEffect, useState } from 'react'
import { getUserByIdApi } from '@/lib/api/users'

interface PermissionsManagerProps {
  sourceId: string
}

interface UserLookupResponse {
  id: string
  email: string
}

async function lookupUserByEmail(email: string): Promise<UserLookupResponse> {
  const { data } = await apiClient.get<UserLookupResponse>(
    `/api/v1/admin/users/lookup?email=${encodeURIComponent(email)}`
  )
  return data
}

export function PermissionsManager({ sourceId }: PermissionsManagerProps) {
  const [email, setEmail] = useState('')
  const [lookupError, setLookupError] = useState<string | null>(null)
  const [isLookingUp, setIsLookingUp] = useState(false)
  const [emailMap, setEmailMap] = useState<Record<string, string>>({})

  const { data: userIds = [], isLoading } = useSourcePermissions(sourceId)

  useEffect(() => {
    if (userIds.length === 0) return
    const newIds = userIds.filter((id) => !(id in emailMap))
    if (newIds.length === 0) return
    newIds.forEach((id) => {
      getUserByIdApi(id)
        .then((u) => setEmailMap((prev) => ({ ...prev, [id]: u.email })))
        .catch(() => setEmailMap((prev) => ({ ...prev, [id]: id.slice(0, 8) + '…' })))
    })
  }, [userIds])

  const grantMutation = useGrantPermission(sourceId)
  const revokeMutation = useRevokePermission(sourceId)

  async function handleGrant() {
    const trimmed = email.trim()
    if (!trimmed) return

    setLookupError(null)
    setIsLookingUp(true)

    try {
      const user = await lookupUserByEmail(trimmed)
      grantMutation.mutate(user.id, {
        onSuccess: () => setEmail(''),
        onError: (err) => setLookupError(err.message ?? 'Failed to grant permission.'),
      })
    } catch (err: unknown) {
      const status =
        err != null &&
        typeof err === 'object' &&
        'response' in err &&
        (err as { response?: { status?: number } }).response?.status
      if (status === 404) {
        setLookupError('User not found.')
      } else {
        setLookupError('Failed to look up user.')
      }
    } finally {
      setIsLookingUp(false)
    }
  }

  if (isLoading) {
    return <div className="py-4 text-center text-muted-foreground">Loading permissions…</div>
  }

  const isPending = isLookingUp || grantMutation.isPending

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex gap-2">
          <Input
            type="email"
            placeholder="User email address"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value)
              setLookupError(null)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleGrant()
            }}
            className="max-w-sm"
            aria-invalid={!!lookupError}
          />
          <Button onClick={handleGrant} disabled={!email.trim() || isPending}>
            <UserPlus className="mr-2 h-4 w-4" />
            {isPending ? 'Granting…' : 'Grant'}
          </Button>
        </div>
        {lookupError && <p className="text-sm text-destructive">{lookupError}</p>}
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
              <span
                className="text-sm"
                title={userId}
              >
                {emailMap[userId] ?? userId.slice(0, 8) + '…'}
              </span>
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
