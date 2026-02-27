'use client'

import { useMutation, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/features/auth/context/AuthContext'
import {
  type ChangePasswordRequest,
  type LoginRequest,
  type PasswordResetConfirmRequest,
  type PasswordResetRequest,
  type SetupAccountRequest,
  type TokenResponse,
  changePasswordApi,
  confirmPasswordResetApi,
  loginApi,
  logoutApi,
  requestPasswordResetApi,
  setupAccountApi,
} from '@/lib/api/auth'

/**
 * Login mutation.
 * On success, the AuthContext is updated via the returned TokenResponse.
 */
export function useLogin() {
  const { setAccessToken } = useAuth()
  return useMutation<TokenResponse, Error, LoginRequest>({
    mutationFn: loginApi,
    onSuccess: (data) => {
      setAccessToken(data.access_token)
    },
  })
}

/**
 * Logout mutation.
 * Clears the in-memory access token and invalidates all queries so any
 * cached user data is dropped.
 */
export function useLogout() {
  const { clearAccessToken } = useAuth()
  const qc = useQueryClient()
  return useMutation<void, Error, void>({
    mutationFn: logoutApi,
    onSettled: () => {
      clearAccessToken()
      qc.clear()
    },
  })
}

/**
 * Accept invitation + set initial password.
 */
export function useSetupAccount() {
  return useMutation<void, Error, SetupAccountRequest>({
    mutationFn: setupAccountApi,
  })
}

/**
 * Request a password-reset email. Always succeeds from the client's
 * perspective (server returns 202 regardless of whether the email exists
 * to prevent enumeration).
 */
export function useRequestPasswordReset() {
  return useMutation<void, Error, PasswordResetRequest>({
    mutationFn: requestPasswordResetApi,
  })
}

/**
 * Submit the reset token + new password.
 */
export function useConfirmPasswordReset() {
  return useMutation<void, Error, PasswordResetConfirmRequest>({
    mutationFn: confirmPasswordResetApi,
  })
}

/**
 * Change password (authenticated).
 * Used both for voluntary change and for forced change when
 * `must_change_password === true`.
 */
export function useChangePassword() {
  return useMutation<void, Error, ChangePasswordRequest>({
    mutationFn: changePasswordApi,
  })
}
