import { apiClient } from '@/lib/api-client'

// ── Request / Response types ─────────────────────────────────────────────────

export interface LoginRequest {
  email: string
  password: string
}

export interface TokenResponse {
  access_token: string
  token_type: 'Bearer'
  expires_in: number
  must_change_password: boolean
}

export interface SetupAccountRequest {
  invitation_token: string
  password: string
}

export interface ChangePasswordRequest {
  current_password?: string // optional: omit when forced by must_change_password
  new_password: string
}

export interface PasswordResetRequest {
  email: string
}

export interface PasswordResetConfirmRequest {
  token: string
  new_password: string
}

// ── API functions ────────────────────────────────────────────────────────────

export async function loginApi(body: LoginRequest): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>('/api/v1/auth/login', body)
  return data
}

export async function refreshTokenApi(): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>('/api/v1/auth/refresh')
  return data
}

export async function logoutApi(): Promise<void> {
  await apiClient.post('/api/v1/auth/logout')
}

export async function setupAccountApi(body: SetupAccountRequest): Promise<void> {
  await apiClient.post('/api/v1/auth/setup', body)
}

export async function requestPasswordResetApi(body: PasswordResetRequest): Promise<void> {
  await apiClient.post('/api/v1/auth/password-reset', body)
}

export async function confirmPasswordResetApi(body: PasswordResetConfirmRequest): Promise<void> {
  await apiClient.post('/api/v1/auth/password-reset/confirm', body)
}

export async function changePasswordApi(body: ChangePasswordRequest): Promise<void> {
  await apiClient.post('/api/v1/auth/change-password', body)
}
