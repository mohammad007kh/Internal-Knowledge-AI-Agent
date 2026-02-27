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

  const scheduleRefresh = useCallback((token: string) => {
    const payload = decodeJwt(token)
    if (!payload) return
    const msUntilExpiry = payload.exp * 1000 - Date.now()
    const refreshIn = Math.max(msUntilExpiry - 60_000, 0)

    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)

    refreshTimerRef.current = setTimeout(async () => {
      try {
        const data = await refreshTokenApi()
        setAccessTokenState(data.access_token)
        scheduleRefresh(data.access_token)
      } catch {
        setAccessTokenState(null)
      }
    }, refreshIn)
  }, [])

  // Initial session restore from httpOnly refresh cookie
  useEffect(() => {
    ;(async () => {
      try {
        const data = await refreshTokenApi()
        setAccessTokenState(data.access_token)
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
  }, [scheduleRefresh])

  // Sync token to module-level store so api-client.ts can read it without React
  useEffect(() => {
    setToken(accessToken)
  }, [accessToken])

  const setAccessToken = useCallback(
    (token: string) => {
      setAccessTokenState(token)
      scheduleRefresh(token)
      // Write readable cookie for Next.js Edge middleware
      const payload = decodeJwt(token)
      if (payload) {
        Cookies.set('__access', token, {
          expires: new Date(payload.exp * 1000),
          sameSite: 'strict',
          secure: process.env.NODE_ENV === 'production',
          // NOT httpOnly — must be readable from middleware
        })
      }
    },
    [scheduleRefresh]
  )

  const clearAccessToken = useCallback(() => {
    setAccessTokenState(null)
    Cookies.remove('__access')
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
