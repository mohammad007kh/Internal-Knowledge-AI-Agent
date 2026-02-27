'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useRequestPasswordReset } from '@/features/auth/hooks/useAuthMutations'

const requestSchema = z.object({
  email: z.string().email('Enter a valid email address'),
})
type RequestFormValues = z.infer<typeof requestSchema>

export default function PasswordResetPage() {
  const [submitted, setSubmitted] = useState(false)
  const requestReset = useRequestPasswordReset()

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RequestFormValues>({ resolver: zodResolver(requestSchema) })

  const onSubmit = async (values: RequestFormValues) => {
    try {
      await requestReset.mutateAsync(values)
    } catch {
      // Always show success to prevent email enumeration (server returns 202)
    } finally {
      setSubmitted(true)
    }
  }

  if (submitted) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Check your inbox</CardTitle>
          <CardDescription>
            If an account exists for that email address, you will receive a password reset link
            within a few minutes.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <a
            href="/auth/login"
            className="text-sm text-muted-foreground hover:text-foreground underline-offset-4 hover:underline"
          >
            ← Back to sign in
          </a>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Reset your password</CardTitle>
        <CardDescription>Enter your email address and we'll send you a reset link</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          <div className="space-y-1">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              aria-invalid={!!errors.email}
              {...register('email')}
            />
            {errors.email && <p className="text-sm text-destructive">{errors.email.message}</p>}
          </div>

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? 'Sending…' : 'Send reset link'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
