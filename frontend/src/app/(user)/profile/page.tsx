'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ErrorState } from '@/components/ui/ErrorState'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { apiClient, parseErrorResponse } from '@/lib/api-client'
import { getErrorMessage } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRoundIcon, MailIcon, ShieldCheckIcon, SlidersHorizontalIcon, UserIcon } from 'lucide-react'
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

type SettingsTab = 'profile' | 'preferences' | 'security'

interface NavItem {
  id: SettingsTab
  label: string
  description: string
  icon: typeof UserIcon
}

const NAV_ITEMS: ReadonlyArray<NavItem> = [
  {
    id: 'profile',
    label: 'Profile',
    description: 'Account details and identity',
    icon: UserIcon,
  },
  {
    id: 'preferences',
    label: 'Preferences',
    description: 'Personalize your experience',
    icon: SlidersHorizontalIcon,
  },
  {
    id: 'security',
    label: 'Security',
    description: 'Password and authentication',
    icon: KeyRoundIcon,
  },
]

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

interface SectionHeaderProps {
  title: string
  description: string
}

function SectionHeader({ title, description }: SectionHeaderProps) {
  return (
    <div className="space-y-1">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      <p className="text-sm text-muted-foreground">{description}</p>
    </div>
  )
}

function SectionDivider() {
  return <div className="h-px w-full bg-border" role="separator" />
}

interface SidebarNavProps {
  active: SettingsTab
  onSelect: (tab: SettingsTab) => void
}

function SidebarNav({ active, onSelect }: SidebarNavProps) {
  return (
    <nav aria-label="Settings sections" className="flex flex-row gap-1 overflow-x-auto lg:flex-col lg:gap-1">
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon
        const isActive = item.id === active
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item.id)}
            aria-current={isActive ? 'page' : undefined}
            className={cn(
              'group flex items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors',
              'whitespace-nowrap lg:whitespace-normal',
              isActive
                ? 'bg-muted font-medium text-foreground'
                : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground'
            )}
          >
            <Icon
              className={cn(
                'h-4 w-4 shrink-0 transition-colors',
                isActive ? 'text-foreground' : 'text-muted-foreground group-hover:text-foreground'
              )}
              aria-hidden="true"
            />
            <span>{item.label}</span>
          </button>
        )
      })}
    </nav>
  )
}

interface ProfileSectionProps {
  data: MeResponse
  fullName: string
  setFullName: (value: string) => void
  onSave: () => void
  isPending: boolean
  nameDirty: boolean
}

function ProfileSection({
  data,
  fullName,
  setFullName,
  onSave,
  isPending,
  nameDirty,
}: ProfileSectionProps) {
  return (
    <div className="space-y-6">
      <SectionHeader title="Profile" description="Your account details and how others identify you." />
      <SectionDivider />

      <div className="grid gap-6 sm:grid-cols-3">
        <div className="sm:col-span-1">
          <Label className="text-sm font-medium">Email</Label>
          <p className="mt-1 text-xs text-muted-foreground">Used for sign-in and notifications.</p>
        </div>
        <div className="sm:col-span-2">
          <div className="flex items-center gap-2 rounded-md border bg-muted/40 px-3 py-2 text-sm">
            <MailIcon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <span className="font-medium">{data.email}</span>
          </div>
        </div>
      </div>

      <SectionDivider />

      <div className="grid gap-6 sm:grid-cols-3">
        <div className="sm:col-span-1">
          <Label className="text-sm font-medium">Role</Label>
          <p className="mt-1 text-xs text-muted-foreground">Determines access across the workspace.</p>
        </div>
        <div className="sm:col-span-2">
          <Badge
            variant={data.role === 'admin' ? 'default' : 'secondary'}
            className="gap-1.5 px-2.5 py-1 capitalize"
          >
            <ShieldCheckIcon className="h-3.5 w-3.5" aria-hidden="true" />
            {data.role}
          </Badge>
        </div>
      </div>

      <SectionDivider />

      <div className="grid gap-6 sm:grid-cols-3">
        <div className="sm:col-span-1">
          <Label htmlFor="full_name" className="text-sm font-medium">
            Display name
          </Label>
          <p className="mt-1 text-xs text-muted-foreground">
            Shown in the app header and chat history.
          </p>
        </div>
        <div className="sm:col-span-2 space-y-3">
          <Input
            id="full_name"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            maxLength={100}
            placeholder="Your name"
          />
          <div className="flex justify-end">
            <Button onClick={onSave} disabled={!nameDirty || isPending} size="sm">
              {isPending ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

interface PreferencesSectionProps {
  showCitations: boolean
  onToggle: (next: boolean) => void
  isPending: boolean
}

function PreferencesSection({ showCitations, onToggle, isPending }: PreferencesSectionProps) {
  return (
    <div className="space-y-6">
      <SectionHeader
        title="Preferences"
        description="Personalize how the assistant behaves for you."
      />
      <SectionDivider />

      <div className="flex items-start justify-between gap-6">
        <div className="space-y-1">
          <Label htmlFor="show_citations" className="text-sm font-medium">
            Show citations by default
          </Label>
          <p className="text-xs text-muted-foreground">
            When enabled, assistant messages include numbered source references inline.
          </p>
        </div>
        <Switch
          id="show_citations"
          checked={showCitations}
          onCheckedChange={onToggle}
          disabled={isPending}
        />
      </div>
    </div>
  )
}

interface SecuritySectionProps {
  currentPassword: string
  newPassword: string
  confirmPassword: string
  pwError: string | null
  isPending: boolean
  setCurrentPassword: (value: string) => void
  setNewPassword: (value: string) => void
  setConfirmPassword: (value: string) => void
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void
}

function SecuritySection({
  currentPassword,
  newPassword,
  confirmPassword,
  pwError,
  isPending,
  setCurrentPassword,
  setNewPassword,
  setConfirmPassword,
  onSubmit,
}: SecuritySectionProps) {
  return (
    <div className="space-y-6">
      <SectionHeader
        title="Security"
        description="You will stay signed in on this device after changing your password."
      />
      <SectionDivider />

      <form onSubmit={onSubmit} className="space-y-5">
        <div className="grid gap-6 sm:grid-cols-3">
          <div className="sm:col-span-1">
            <Label htmlFor="current_password" className="text-sm font-medium">
              Current password
            </Label>
          </div>
          <div className="sm:col-span-2">
            <Input
              id="current_password"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </div>
        </div>

        <SectionDivider />

        <div className="grid gap-6 sm:grid-cols-3">
          <div className="sm:col-span-1">
            <Label htmlFor="new_password" className="text-sm font-medium">
              New password
            </Label>
            <p className="mt-1 text-xs text-muted-foreground">Minimum 8 characters.</p>
          </div>
          <div className="sm:col-span-2">
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
        </div>

        <div className="grid gap-6 sm:grid-cols-3">
          <div className="sm:col-span-1">
            <Label htmlFor="confirm_password" className="text-sm font-medium">
              Confirm new password
            </Label>
          </div>
          <div className="sm:col-span-2">
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
        </div>

        {pwError && (
          <p className="text-sm text-destructive" role="alert">
            {pwError}
          </p>
        )}

        <div className="flex justify-end">
          <Button type="submit" disabled={isPending}>
            {isPending ? 'Updating…' : 'Change password'}
          </Button>
        </div>
      </form>
    </div>
  )
}

export default function ProfilePage() {
  const { data, isLoading, isError, error, refetch } = useMe()
  const update = useUpdateMe()

  const [activeTab, setActiveTab] = useState<SettingsTab>('profile')
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
      <div className="space-y-6 p-6">
        <div className="space-y-2">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-4 w-72" />
        </div>
        <div className="grid gap-8 lg:grid-cols-[220px_1fr]">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-96 w-full" />
        </div>
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

  const activeNavItem = NAV_ITEMS.find((item) => item.id === activeTab) ?? NAV_ITEMS[0]

  return (
    <div className="mx-auto w-full max-w-5xl space-y-8 p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">
          Manage your account, preferences, and security from one place.
        </p>
      </header>

      <div className="grid gap-8 lg:grid-cols-[220px_1fr]">
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <SidebarNav active={activeTab} onSelect={setActiveTab} />
          <p className="mt-3 hidden text-xs text-muted-foreground lg:block">
            {activeNavItem.description}
          </p>
        </aside>

        <Card>
          <CardContent className="p-6 sm:p-8">
            {activeTab === 'profile' && (
              <ProfileSection
                data={data}
                fullName={fullName}
                setFullName={setFullName}
                onSave={saveName}
                isPending={update.isPending}
                nameDirty={nameDirty}
              />
            )}
            {activeTab === 'preferences' && (
              <PreferencesSection
                showCitations={data.show_citations_preference}
                onToggle={toggleCitations}
                isPending={update.isPending}
              />
            )}
            {activeTab === 'security' && (
              <SecuritySection
                currentPassword={currentPassword}
                newPassword={newPassword}
                confirmPassword={confirmPassword}
                pwError={pwError}
                isPending={update.isPending}
                setCurrentPassword={setCurrentPassword}
                setNewPassword={setNewPassword}
                setConfirmPassword={setConfirmPassword}
                onSubmit={submitPassword}
              />
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
