'use client'

import {
  grantPermissionApi,
  listSourcePermissionsApi,
  revokePermissionApi,
} from '@/lib/api/sources'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

const permissionsKey = (sourceId: string) => ['source-permissions', sourceId] as const

export function useSourcePermissions(sourceId: string) {
  return useQuery({
    queryKey: permissionsKey(sourceId),
    queryFn: () => listSourcePermissionsApi(sourceId),
    enabled: !!sourceId,
  })
}

export function useGrantPermission(sourceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => grantPermissionApi(sourceId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: permissionsKey(sourceId) })
      toast.success('Permission granted')
    },
    onError: () => {
      toast.error('Failed to grant permission')
    },
  })
}

export function useRevokePermission(sourceId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => revokePermissionApi(sourceId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: permissionsKey(sourceId) })
      toast.success('Permission revoked')
    },
    onError: () => {
      toast.error('Failed to revoke permission')
    },
  })
}
