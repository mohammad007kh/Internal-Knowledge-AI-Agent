export type UserRole = 'admin' | 'user'

export interface AuthUser {
  id: string
  email: string
  role: UserRole
  must_change_password: boolean
}

export interface AuthContextValue {
  /** Decoded JWT payload; null when unauthenticated. */
  user: AuthUser | null
  /** Raw access token (opaque to most callers). */
  accessToken: string | null
  /** True while the initial refresh call is in-flight. */
  isLoading: boolean
  /** Store a new access token (called by login/refresh mutations). */
  setAccessToken: (token: string) => void
  /** Clear the token (called by logout mutation). */
  clearAccessToken: () => void
}
