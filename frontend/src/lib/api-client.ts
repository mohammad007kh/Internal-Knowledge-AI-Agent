import { getToken, setToken } from '@/lib/token-store'
import axios from 'axios'
import Cookies from 'js-cookie'

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export const apiClient = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
})

// RFC 7807 Problem Details for HTTP APIs
export interface ProblemDetail {
  type?: string
  title?: string
  status: number
  detail?: string
  instance?: string
}

export function parseErrorResponse(error: unknown): Error {
  if (axios.isAxiosError(error) && error.response) {
    const contentType = (error.response.headers?.['content-type'] as string) ?? ''
    if (contentType.includes('application/problem+json')) {
      const problem = error.response.data as ProblemDetail
      return new Error(problem.detail ?? problem.title ?? 'An error occurred')
    }
  }
  if (error instanceof Error) return error
  return new Error('An unexpected error occurred')
}

// Request interceptor — inject Bearer token from in-memory token store
apiClient.interceptors.request.use((config) => {
  const token = getToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor — parse RFC 7807 errors, then on 401 attempt refresh and retry once
let isRefreshing = false
type QueuedWaiter = {
  resolve: (token: string) => void
  reject: (error: unknown) => void
}
let refreshQueue: QueuedWaiter[] = []

function flushQueue(token: string | null, error?: unknown): void {
  for (const waiter of refreshQueue) {
    if (token) waiter.resolve(token)
    else waiter.reject(error)
  }
  refreshQueue = []
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    // Parse RFC 7807 ProblemDetail before any retry logic so callers receive
    // a human-readable Error message regardless of status code.
    const contentType = (error.response?.headers?.['content-type'] as string) ?? ''
    if (
      error.response &&
      error.response.status !== 401 &&
      contentType.includes('application/problem+json')
    ) {
      return Promise.reject(parseErrorResponse(error))
    }

    const original = error.config

    // Never retry auth endpoints. /auth/refresh would loop; /auth/login and
    // /auth/logout are unauthenticated by design — a 401 there is not a
    // session-expired signal, it's a credentials/state error that must
    // surface to the caller verbatim. Without this guard, a wrong-password
    // 401 on /auth/login would silently trigger a refresh attempt and the
    // refresh's error message ("Invalid or expired refresh token") would
    // mask the real login error in the UI toast.
    const noRetryUrls = ['/auth/refresh', '/auth/login', '/auth/logout']
    const isAuthEndpoint = noRetryUrls.some((u) => original?.url?.includes(u))
    if (error.response?.status !== 401 || original._retried || isAuthEndpoint) {
      // For auth endpoints with problem+json bodies, parse so callers get
      // the human-readable detail rather than axios's generic error message.
      if (isAuthEndpoint && contentType.includes('application/problem+json')) {
        return Promise.reject(parseErrorResponse(error))
      }
      return Promise.reject(error)
    }

    original._retried = true

    if (isRefreshing) {
      return new Promise((resolve, reject) => {
        refreshQueue.push({
          resolve: (token: string) => {
            original.headers.Authorization = `Bearer ${token}`
            resolve(apiClient(original))
          },
          reject,
        })
      })
    }

    isRefreshing = true

    try {
      const { data } = await axios.post<{ access_token: string }>(
        `${BASE_URL}/api/v1/auth/refresh`,
        {},
        { withCredentials: true }
      )

      const newToken = data.access_token

      // Persist refreshed token to the in-memory store so subsequent requests
      // (including raw fetch() callers like the chat SSE stream) pick it up
      // immediately. Without this, every new request re-enters the 401 cycle
      // and re-triggers a refresh — which can hit the backend rate-limit and
      // cascade into a navigation loop between /chat and /login.
      setToken(newToken)

      // Flush queued requests with the fresh token
      flushQueue(newToken)

      original.headers.Authorization = `Bearer ${newToken}`
      return apiClient(original)
    } catch (refreshError) {
      // Reject every concurrent waiter so their callers see the failure
      // immediately instead of hanging on a never-resolved promise (which
      // surfaces as an infinite UI spinner).
      flushQueue(null, refreshError)
      // Refresh failed (expired/missing refresh cookie OR rate-limited 429).
      // Clear *both* the in-memory access token and the JS-readable __access
      // cookie. The Edge middleware decides authentication state from the
      // cookie — if we leave it in place while navigating to /login, the
      // middleware sees a valid JWT and immediately redirects back to /chat,
      // which remounts and re-triggers the same 401 → refresh → 429 cycle.
      setToken(null)
      if (typeof window !== 'undefined') {
        // Match the path used at set-time so js-cookie reliably clears it.
        Cookies.remove('__access', { path: '/' })
        if (!window.location.pathname.startsWith('/login')) {
          window.location.href = '/login'
        }
      }
      return Promise.reject(parseErrorResponse(refreshError))
    } finally {
      isRefreshing = false
    }
  }
)
