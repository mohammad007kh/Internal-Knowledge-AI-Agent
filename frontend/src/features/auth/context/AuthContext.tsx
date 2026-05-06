'use client'

import { refreshTokenApi } from '@/lib/api/auth'
import { setToken } from '@/lib/token-store'
import Cookies from 'js-cookie'
import {
  type ReactNode,
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react'
import type { AuthContextValue, AuthUser } from '../types'

interface JwtPayload {
  sub: string
  email: string
  role: 'admin' | 'user'
  must_change_password?: boolean
  exp: number
}

function decodeJwt(token: string): JwtPayload | null {
  try {
    const [, payload] = token.split('.')
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    return JSON.parse(json) as JwtPayload
  } catch {
    return null
  }
}

function jwtToUser(token: string): AuthUser | null {
  const payload = decodeJwt(token)
  if (!payload) return null
  return {
    id: payload.sub,
    email: payload.email,
    role: payload.role,
    must_change_password: payload.must_change_password ?? false,
  }
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [accessToken, setAccessTokenState] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  const user: AuthUser | null = accessToken ? jwtToUser(accessToken) : null

  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Single helper for writing the JS-readable __access cookie that Edge
  // middleware gates protected routes on. Every code path that sets
  // accessToken state MUST also call this — otherwise middleware can't see
  // the session and bounces /chat → /login while React state thinks the
  // user is authenticated. Gates Secure on the actual page scheme (not on
  // NODE_ENV) so a production build served over plain HTTP localhost can
  // still write the cookie.
  const writeAccessCookie = useCallback((token: string) => {
    const payload = decodeJwt(token)
    if (!payload) return
    Cookies.set('__access', token, {
      expires: new Date(payload.exp * 1000),
      path: '/',
      sameSite: 'strict',
      secure: typeof window !== 'undefined' && window.location.protocol === 'https:',
    })
  }, [])

  const scheduleRefresh = useCallback(
    (token: string) => {
      const payload = decodeJwt(token)
      if (!payload) return
      const msUntilExpiry = payload.exp * 1000 - Date.now()
      const refreshIn = Math.max(msUntilExpiry - 60_000, 0)

      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)

      refreshTimerRef.current = setTimeout(async () => {
        try {
          const data = await refreshTokenApi()
          setAccessTokenState(data.access_token)
          writeAccessCookie(data.access_token)
          scheduleRefresh(data.access_token)
        } catch {
          // Scheduled refresh failed — drop both the in-memory token *and* the
          // JS-readable __access cookie. Leaving a stale cookie behind makes the
          // Edge middleware think we are still authenticated, which cancels any
          // /login redirect and reloads /chat, triggering another 401 cycle.
          setAccessTokenState(null)
          Cookies.remove('__access', { path: '/' })
        }
      }, refreshIn)
    },
    [writeAccessCookie]
  )

  // Initial session restore from httpOnly refresh cookie. The cookie write
  // matters: Edge middleware gates /chat etc. on the __access cookie, so an
  // auto-restored session that didn't write the cookie would leave the user
  // unable to navigate anywhere protected even though `user` was truthy in
  // React state — that bug presented to users as "I click Sign in and
  // nothing happens" because the LoginPage useEffect would fire
  // router.replace('/chat') and middleware would bounce it right back.
  useEffect(() => {
    ;(async () => {
      try {
        const data = await refreshTokenApi()
        setAccessTokenState(data.access_token)
        writeAccessCookie(data.access_token)
        scheduleRefresh(data.access_token)
      } catch {
        // No valid session — remain unauthenticated
      } finally {
        setIsLoading(false)
      }
    })()

    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    }
  }, [scheduleRefresh, writeAccessCookie])

  // Sync token to module-level store so api-client.ts can read it without React
  useEffect(() => {
    setToken(accessToken)
  }, [accessToken])

  const setAccessToken = useCallback(
    (token: string) => {
      setAccessTokenState(token)
      writeAccessCookie(token)
      scheduleRefresh(token)
    },
    [scheduleRefresh, writeAccessCookie]
  )

  const clearAccessToken = useCallback(() => {
    setAccessTokenState(null)
    Cookies.remove('__access', { path: '/' })
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
  }, [])

  return (
    <AuthContext.Provider
      value={{ user, accessToken, isLoading, setAccessToken, clearAccessToken }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used inside <AuthProvider>')
  }
  return ctx
}
