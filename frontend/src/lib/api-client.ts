import { getToken } from '@/lib/token-store'
import axios from 'axios'

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
let refreshQueue: Array<(token: string) => void> = []

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

    if (error.response?.status !== 401 || original._retried) {
      return Promise.reject(error)
    }

    original._retried = true

    if (isRefreshing) {
      return new Promise((resolve) => {
        refreshQueue.push((token: string) => {
          original.headers.Authorization = `Bearer ${token}`
          resolve(apiClient(original))
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

      // Flush queued requests
      for (const cb of refreshQueue) cb(newToken)
      refreshQueue = []

      original.headers.Authorization = `Bearer ${newToken}`
      return apiClient(original)
    } catch (refreshError) {
      refreshQueue = []
      if (typeof window !== 'undefined') {
        window.location.href = '/login'
      }
      return Promise.reject(parseErrorResponse(refreshError))
    } finally {
      isRefreshing = false
    }
  }
)
