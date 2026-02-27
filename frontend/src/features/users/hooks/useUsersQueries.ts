'use client'

import {
  type ChangeRoleRequest,
  type InviteUserRequest,
  changeUserRoleApi,
  deactivateUserApi,
  inviteUserApi,
  listUsersApi,
} from '@/lib/api/users'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

const USERS_KEY = ['admin', 'users'] as const

export function useUsersList(limit = 50, offset = 0) {
  return useQuery({
    queryKey: [...USERS_KEY, limit, offset],
    queryFn: () => listUsersApi(limit, offset),
  })
}

export function useInviteUser() {
  const qc = useQueryClient()
  return useMutation<void, Error, InviteUserRequest>({
    mutationFn: inviteUserApi,
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  })
}

export function useChangeRole() {
  const qc = useQueryClient()
  return useMutation<
    Awaited<ReturnType<typeof changeUserRoleApi>>,
    Error,
    { userId: string; body: ChangeRoleRequest }
  >({
    mutationFn: ({ userId, body }) => changeUserRoleApi(userId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  })
}

export function useDeactivateUser() {
  const qc = useQueryClient()
  return useMutation<void, Error, string>({
    mutationFn: deactivateUserApi,
    onSuccess: () => qc.invalidateQueries({ queryKey: USERS_KEY }),
  })
}
