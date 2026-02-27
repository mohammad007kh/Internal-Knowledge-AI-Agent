'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useRouter } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/features/auth/context/AuthContext'
import { useChangePassword } from '@/features/auth/hooks/useAuthMutations'

const passwordRules = z
  .string()
  .min(8, 'Password must be at least 8 characters')
  .regex(/[A-Z]/, 'Must contain at least one uppercase letter')
  .regex(/[a-z]/, 'Must contain at least one lowercase letter')
  .regex(/[0-9]/, 'Must contain at least one number')

const forcedSchema = z
  .object({
    new_password: passwordRules,
    confirm_password: z.string().min(1, 'Please confirm your password'),
  })
  .refine((d) => d.new_password === d.confirm_password, {
    path: ['confirm_password'],
    message: 'Passwords do not match',
  })

const voluntarySchema = forcedSchema.and(
  z.object({ current_password: z.string().min(1, 'Current password is required') })
)

type ForcedFormValues = z.infer<typeof forcedSchema>
type VoluntaryFormValues = z.infer<typeof voluntarySchema>
type FormValues = ForcedFormValues | VoluntaryFormValues

export default function ChangePasswordPage() {
  const router = useRouter()
  const { user } = useAuth()
  const changePassword = useChangePassword()

  const forced = user?.must_change_password ?? false
  const schema = forced ? forcedSchema : voluntarySchema

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) })

  const onSubmit = async (values: FormValues) => {
    try {
      await changePassword.mutateAsync({
        new_password: (values as ForcedFormValues).new_password,
        current_password: (values as VoluntaryFormValues).current_password,
      })
      toast.success('Password changed successfully')
      router.push('/chat')
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Failed to change password. Please try again.'
      toast.error(message)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{forced ? 'Set a new password' : 'Change password'}</CardTitle>
        <CardDescription>
          {forced
            ? 'You must set a new password before continuing.'
            : 'Update your account password.'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          {!forced && (
            <div className="space-y-1">
              <Label htmlFor="current_password">Current password</Label>
              <Input
                id="current_password"
                type="password"
                autoComplete="current-password"
                aria-invalid={!!(errors as { current_password?: unknown }).current_password}
                {...register('current_password' as keyof FormValues)}
              />
              {(errors as { current_password?: { message?: string } }).current_password && (
                <p className="text-sm text-destructive">
                  {
                    (errors as { current_password?: { message?: string } }).current_password
                      ?.message
                  }
                </p>
              )}
            </div>
          )}
          <div className="space-y-1">
            <Label htmlFor="new_password">New password</Label>
            <Input
              id="new_password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!(errors as { new_password?: unknown }).new_password}
              {...register('new_password' as keyof FormValues)}
            />
            {(errors as { new_password?: { message?: string } }).new_password && (
              <p className="text-sm text-destructive">
                {(errors as { new_password?: { message?: string } }).new_password?.message}
              </p>
            )}
          </div>
          <div className="space-y-1">
            <Label htmlFor="confirm_password">Confirm new password</Label>
            <Input
              id="confirm_password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!(errors as { confirm_password?: unknown }).confirm_password}
              {...register('confirm_password' as keyof FormValues)}
            />
            {(errors as { confirm_password?: { message?: string } }).confirm_password && (
              <p className="text-sm text-destructive">
                {(errors as { confirm_password?: { message?: string } }).confirm_password?.message}
              </p>
            )}
          </div>
          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? 'Saving…' : 'Change password'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
