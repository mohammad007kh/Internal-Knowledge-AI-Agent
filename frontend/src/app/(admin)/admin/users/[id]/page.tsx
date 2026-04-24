'use client'

import type { AdminUser } from '@/components/admin/UsersTable'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { usersKeys } from '@/features/users/hooks/useUsersQueries'
import { apiClient } from '@/lib/api-client'
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams, useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

const schema = z.object({
  full_name: z.string().max(100).optional(),
  email: z.string().email(),
  role: z.enum(['admin', 'user']),
})
type FormValues = z.infer<typeof schema>

export default function UserDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const queryClient = useQueryClient()

  const { data: user, isLoading, isError } = useQuery({
    queryKey: usersKeys.detail(id),
    queryFn: async () => {
      const res = await apiClient.get<AdminUser>(`/api/v1/users/${id}`)
      return res.data
    },
  })

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    values: user
      ? {
          full_name: user.full_name ?? '',
          email: user.email,
          role: user.role,
        }
      : undefined,
  })

  const updateMutation = useMutation({
    mutationFn: (v: FormValues) => apiClient.patch(`/api/v1/users/${id}`, v),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
      toast.success('User updated.')
    },
    onError: () => toast.error('Failed to update user.'),
  })

  const toggleActiveMutation = useMutation({
    mutationFn: (active: boolean) => apiClient.patch(`/api/v1/users/${id}`, { is_active: active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })
      toast.success(user?.is_active ? 'User deactivated.' : 'User reactivated.')
    },
  })

  const resetPasswordMutation = useMutation({
    mutationFn: () => apiClient.post(`/api/v1/users/${id}/reset-password`),
    onSuccess: () => toast.success('Password reset email sent.'),
    onError: () => toast.error('Failed to send reset email.'),
  })

  if (isLoading) {
    return <div className="h-64 animate-pulse rounded-md bg-muted" aria-busy="true" />
  }

  if (isError || !user) {
    return (
      <div className="flex flex-col items-center gap-3 p-6 text-center">
        <p className="font-medium text-destructive">Failed to load user.</p>
        <Button variant="outline" size="sm" onClick={() => router.push('/admin/users')}>
          Back to users
        </Button>
      </div>
    )
  }

  return (
    <div className="max-w-xl space-y-8 p-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">{user.full_name ?? user.email}</h1>
          <p className="text-sm text-muted-foreground">{user.email}</p>
        </div>
        <Badge variant={user.is_active ? 'outline' : 'secondary'}>
          {user.is_active ? 'Active' : 'Inactive'}
        </Badge>
      </div>

      <div className="border-t" />

      {/* Edit profile */}
      <section aria-label="Edit profile">
        <h2 className="mb-4 text-sm font-medium">Profile</h2>
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit((v) => updateMutation.mutate(v))}
            className="space-y-4"
            noValidate
          >
            <FormField
              control={form.control}
              name="full_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Full name</FormLabel>
                  <FormControl>
                    <Input {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Email</FormLabel>
                  <FormControl>
                    <Input type="email" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="role"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Role</FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value="user">User</SelectItem>
                      <SelectItem value="admin">Admin</SelectItem>
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />
            <div className="flex gap-2">
              <Button type="submit" size="sm" disabled={updateMutation.isPending}>
                Save changes
              </Button>
              <Button type="button" size="sm" variant="ghost" onClick={() => router.back()}>
                Cancel
              </Button>
            </div>
          </form>
        </Form>
      </section>

      <div className="border-t" />

      {/* Account status */}
      <section aria-label="Account status">
        <h2 className="mb-2 text-sm font-medium">Account</h2>
        <div className="flex flex-wrap gap-2">
          <Button
            variant={user.is_active ? 'destructive' : 'outline'}
            size="sm"
            disabled={toggleActiveMutation.isPending}
            onClick={() => toggleActiveMutation.mutate(!user.is_active)}
          >
            {user.is_active ? 'Deactivate account' : 'Reactivate account'}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={resetPasswordMutation.isPending}
            onClick={() => resetPasswordMutation.mutate()}
          >
            Send password reset
          </Button>
        </div>
      </section>

      <div className="border-t" />

      {/* Activity */}
      <section aria-label="Activity">
        <h2 className="mb-2 text-sm font-medium">Activity</h2>
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <dt className="text-muted-foreground">Last login</dt>
          <dd>{user.last_login_at ? new Date(user.last_login_at).toLocaleString() : 'Never'}</dd>
          <dt className="text-muted-foreground">Account created</dt>
          <dd>{new Date(user.created_at).toLocaleDateString()}</dd>
        </dl>
      </section>
    </div>
  )
}
