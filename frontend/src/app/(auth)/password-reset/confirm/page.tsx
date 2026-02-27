'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useRouter, useSearchParams } from 'next/navigation'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useConfirmPasswordReset } from '@/features/auth/hooks/useAuthMutations'

const confirmSchema = z
  .object({
    password: z
      .string()
      .min(8, 'Password must be at least 8 characters')
      .regex(/[A-Z]/, 'Must contain at least one uppercase letter')
      .regex(/[a-z]/, 'Must contain at least one lowercase letter')
      .regex(/[0-9]/, 'Must contain at least one number'),
    confirm_password: z.string().min(1, 'Please confirm your password'),
  })
  .refine((d) => d.password === d.confirm_password, {
    path: ['confirm_password'],
    message: 'Passwords do not match',
  })
type ConfirmFormValues = z.infer<typeof confirmSchema>

export default function PasswordResetConfirmPage() {
  const params = useSearchParams()
  const router = useRouter()
  const resetToken = params.get('token') ?? ''
  const confirmReset = useConfirmPasswordReset()

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<ConfirmFormValues>({ resolver: zodResolver(confirmSchema) })

  if (!resetToken) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Invalid link</CardTitle>
          <CardDescription>
            This reset link is missing or malformed. Please request a new one.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <a href="/auth/password-reset" className="text-sm underline">
            Request a new link →
          </a>
        </CardContent>
      </Card>
    )
  }

  const onSubmit = async (values: ConfirmFormValues) => {
    try {
      await confirmReset.mutateAsync({
        token: resetToken,
        new_password: values.password,
      })
      toast.success('Password reset successful. Please sign in.')
      router.push('/auth/login')
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Reset failed. The link may have expired.'
      toast.error(message)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Set new password</CardTitle>
        <CardDescription>Choose a strong password for your account</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="password">New password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!errors.password}
              {...register('password')}
            />
            {errors.password && (
              <p className="text-sm text-destructive">{errors.password.message}</p>
            )}
          </div>

          <div className="space-y-1">
            <Label htmlFor="confirm_password">Confirm password</Label>
            <Input
              id="confirm_password"
              type="password"
              autoComplete="new-password"
              aria-invalid={!!errors.confirm_password}
              {...register('confirm_password')}
            />
            {errors.confirm_password && (
              <p className="text-sm text-destructive">{errors.confirm_password.message}</p>
            )}
          </div>

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? 'Resetting…' : 'Reset password'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
