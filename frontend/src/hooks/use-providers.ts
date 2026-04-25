'use client'

import { apiClient, parseErrorResponse } from '@/lib/api-client'
import type { ProviderCatalog, ProviderSpec } from '@/types/provider'
import { useQuery } from '@tanstack/react-query'

/**
 * Provider catalog is static metadata. Cache aggressively — admins shouldn't
 * see staleness here, but it changes only when the backend ships a new build.
 */
const STALE_TIME = 1000 * 60 * 60 // 1 hour
const GC_TIME = 1000 * 60 * 60 * 24 // 24 hours

const PROVIDERS_KEY = ['admin', 'providers'] as const

async function fetchProviders(): Promise<ProviderCatalog> {
  try {
    const { data } = await apiClient.get<ProviderCatalog>('/api/v1/admin/providers')
    return data
  } catch (error: unknown) {
    throw parseErrorResponse(error)
  }
}

export function useProviders() {
  return useQuery({
    queryKey: PROVIDERS_KEY,
    queryFn: fetchProviders,
    staleTime: STALE_TIME,
    gcTime: GC_TIME,
    // Provider catalog changes only on backend deploy.
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
}

/** Convenience: returns a single provider spec by key, or undefined. */
export function useProvider(key: string | null | undefined): ProviderSpec | undefined {
  const { data } = useProviders()
  if (!key || !data) return undefined
  return data.providers.find((p) => p.key === key)
}
