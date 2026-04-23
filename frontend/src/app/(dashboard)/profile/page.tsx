'use client'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/ui/ErrorState'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { apiClient, parseErrorResponse } from '@/lib/api-client'
import { getErrorMessage } from '@/lib/errors'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { MailIcon, ShieldCheckIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'

interface MeResponse {
  id: string
  email: string
  full_name: string | null
  role: 'admin' | 'user'
  show_citations_preference: boolean
  created_at: string
}

interface UpdateMeRequest {
  full_name?: string
  show_citations_preference?: boolean
  current_password?: string
  new_password?: string
}

async function getMe(): Promise<MeResponse> {
  const { data } = await apiClient.get<MeResponse>('/api/v1/users/me')
  return data
}

async function updateMe(body: UpdateMeRequest): Promise<MeResponse> {
  try {
    const { data } = await apiClient.patch<MeResponse>('/api/v1/users/me', body)
    return data
  } catch (error) {
    throw parseErrorResponse(error)
  }
}

function useMe() {
  return useQuery({ queryKey: ['me'], queryFn: getMe })
}

function useUpdateMe() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: updateMe,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['me'] })
    },
  })
}

export default function ProfilePage() {
  const { data, isLoading, isError, error, refetch } = useMe()
  const update = useUpdateMe()

  const [fullName, setFullName] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [pwError, setPwError] = useState<string | null>(null)

  useEffect(() => {
    if (data) setFullName(data.full_name ?? '')
  }, [data])

  if (isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-64 w-full max-w-2xl" />
        <Skeleton className="h-40 w-full max-w-2xl" />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div className="p-6">
        <ErrorState message={getErrorMessage(error)} onRetry={() => refetch()} />
      </div>
    )
  }

  const nameDirty = fullName.trim() !== (data.full_name ?? '')

  function saveName() {
    update.mutate(
      { full_name: fullName.trim() },
      {
        onSuccess: () => toast.success('Profile updated'),
        onError: (err) => toast.error(getErrorMessage(err)),
      }
    )
  }

  function toggleCitations(next: boolean) {
    update.mutate(
      { show_citations_preference: next },
      {
        onSuccess: () =>
          toast.success(next ? 'Citations shown by default' : 'Citations hidden by default'),
        onError: (err) => toast.error(getErrorMessage(err)),
      }
    )
  }

  function submitPassword(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPwError(null)

    if (newPassword.length < 8) {
      setPwError('New password must be at least 8 characters.')
      return
    }
    if (newPassword !== confirmPassword) {
      setPwError('New password and confirmation do not match.')
      return
    }

    update.mutate(
      { current_password: currentPassword, new_password: newPassword },
      {
        onSuccess: () => {
          setCurrentPassword('')
          setNewPassword('')
          setConfirmPassword('')
          toast.success('Password changed')
        },
        onError: (err) => setPwError(getErrorMessage(err)),
      }
    )
  }

  return (
    <div className="space-y-6 p-6 max-w-2xl">
      <h1 className="text-xl font-semibold">Profile</h1>

      <Card>
        <CardHeader>
          <CardTitle>Profile info</CardTitle>
          <CardDescription>Your account details.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3 text-sm">
            <MailIcon className="h-4 w-4 text-muted-foreground" />
            <span className="text-muted-foreground">Email</span>
            <span className="font-medium">{data.email}</span>
          </div>
          <div className="flex items-center gap-3 text-sm">
            <ShieldCheckIcon className="h-4 w-4 text-muted-foreground" />
            <span className="text-muted-foreground">Role</span>
            <span className="font-medium capitalize">{data.role}</span>
          </div>
          <div className="space-y-2">
            <Label htmlFor="full_name">Display name</Label>
            <Input
              id="full_name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              maxLength={100}
            />
            <Button
              onClick={saveName}
              disabled={!nameDirty || update.isPending}
              size="sm"
            >
              {update.isPending ? 'Saving…' : 'Save'}
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Preferences</CardTitle>
          <CardDescription>Personalize your chat experience.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div className="space-y-0.5">
              <Label htmlFor="show_citations" className="text-sm">
                Show citations by default
              </Label>
              <p className="text-xs text-muted-foreground">
                When enabled, assistant messages include numbered source references.
              </p>
            </div>
            <Switch
              id="show_citations"
              checked={data.show_citations_preference}
              onCheckedChange={toggleCitations}
              disabled={update.isPending}
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Change password</CardTitle>
          <CardDescription>
            You will stay signed in on this device after changing your password.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submitPassword} className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="current_password">Current password</Label>
              <Input
                id="current_password"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new_password">New password</Label>
              <Input
                id="new_password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={8}
                autoComplete="new-password"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm_password">Confirm new password</Label>
              <Input
                id="confirm_password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                minLength={8}
                autoComplete="new-password"
              />
            </div>
            {pwError && (
              <p className="text-sm text-destructive" role="alert">
                {pwError}
              </p>
            )}
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? 'Updating…' : 'Change password'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
