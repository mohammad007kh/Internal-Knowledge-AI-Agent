import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const clearAccessTokenMock = vi.fn()
const logoutApiMock = vi.fn<() => Promise<void>>()

vi.mock('@/features/auth/context/AuthContext', () => ({
  useAuth: () => ({
    user: null,
    accessToken: null,
    isLoading: false,
    setAccessToken: vi.fn(),
    clearAccessToken: clearAccessTokenMock,
  }),
}))

vi.mock('@/lib/api/auth', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api/auth')>()
  return { ...actual, logoutApi: () => logoutApiMock() }
})

import { useLogout } from '../useAuthMutations'

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}

describe('useLogout', () => {
  let replaceSpy: ReturnType<typeof vi.fn>
  let originalLocationDescriptor: PropertyDescriptor | undefined

  beforeEach(() => {
    clearAccessTokenMock.mockReset()
    logoutApiMock.mockReset()
    // jsdom's window.location.replace is a no-op stub; swap in a spy. Save
    // the original descriptor so afterEach can restore it — otherwise the
    // override leaks to every test file that runs after this one in the
    // same worker (configurable:true is not undone by restoreAllMocks).
    originalLocationDescriptor = Object.getOwnPropertyDescriptor(window, 'location')
    replaceSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, replace: replaceSpy },
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    if (originalLocationDescriptor) {
      Object.defineProperty(window, 'location', originalLocationDescriptor)
    }
  })

  it('clears the token and redirects to /login on a successful logout', async () => {
    logoutApiMock.mockResolvedValue(undefined)
    const { result } = renderHook(() => useLogout(), { wrapper })

    await act(async () => {
      result.current.mutate()
    })

    await waitFor(() => expect(clearAccessTokenMock).toHaveBeenCalledTimes(1))
    expect(replaceSpy).toHaveBeenCalledWith('/login')
  })

  it('still clears the token and redirects even when the server logout fails', async () => {
    logoutApiMock.mockRejectedValue(new Error('network down'))
    const { result } = renderHook(() => useLogout(), { wrapper })

    await act(async () => {
      result.current.mutate()
    })

    await waitFor(() => expect(replaceSpy).toHaveBeenCalledWith('/login'))
    expect(clearAccessTokenMock).toHaveBeenCalledTimes(1)
  })
})
