'use client'

import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
  FormDescription,
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
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

const schema = z.object({
  email: z.string().email('Valid email required'),
  full_name: z.string().max(100).optional(),
  role: z.enum(['admin', 'user']),
  send_invite: z.boolean().default(true),
})

type FormValues = z.infer<typeof schema>

async function inviteUser(values: FormValues): Promise<{ id: string }> {
  const res = await apiClient.post<{ id: string }>('/api/v1/users/invitations', values)
  return res.data
}

export default function InviteUserPage() {
  const router = useRouter()
  const queryClient = useQueryClient()

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { role: 'user', send_invite: true },
  })

  const mutation = useMutation({
    mutationFn: inviteUser,
    onSuccess: () => {
      // Refresh pending-invitations badge, the users list (in case the
      // backend creates a shell row), and analytics tiles.
      queryClient.invalidateQueries({ queryKey: usersKeys.invitations() })
      queryClient.invalidateQueries({ queryKey: usersKeys.all })
      queryClient.invalidateQueries({ queryKey: ['admin', 'analytics'] })

      toast.success('Invitation sent successfully.')
      // Note: inviteUser returns an *invitation* id, not a user id, so we
      // cannot safely navigate to /admin/users/:id — redirect to the list
      // where the new invitation will appear under the Invitations tab.
      router.push('/admin/users')
    },
    onError: () => toast.error('Failed to invite user.'),
  })

  return (
    <div className="max-w-lg p-4 md:p-6">
      <h1 className="mb-6 text-xl font-semibold">Invite User</h1>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit((v) => mutation.mutate(v))}
          className="space-y-4"
          noValidate
        >
          <FormField
            control={form.control}
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Email address</FormLabel>
                <FormControl>
                  <Input type="email" placeholder="user@company.com" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="full_name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>
                  Full name <span className="font-normal text-muted-foreground">(optional)</span>
                </FormLabel>
                <FormControl>
                  <Input placeholder="Jane Doe" {...field} />
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
                <Select onValueChange={field.onChange} defaultValue={field.value}>
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
                <FormDescription>Admins can manage sources and other users.</FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />

          <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="outline"
              className="w-full sm:w-auto"
              onClick={() => router.back()}
            >
              Cancel
            </Button>
            <Button type="submit" className="w-full sm:w-auto" disabled={mutation.isPending}>
              {mutation.isPending ? 'Sending…' : 'Send invite'}
            </Button>
          </div>
        </form>
      </Form>
    </div>
  )
}
