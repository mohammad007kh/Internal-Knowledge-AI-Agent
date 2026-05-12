'use client'

import {
  type ChangeRoleRequest,
  type InviteUserRequest,
  type ListUsersParams,
  type UserStatusFilter,
  changeUserRoleApi,
  deactivateUserApi,
  inviteUserApi,
  listUsersApi,
  reactivateUserApi,
} from '@/lib/api/users'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

/**
 * Canonical query-key factory for all user / invitation / admin-users
 * related queries.
 *
 * Structure:
 *   ['admin-users']                                 ← root (invalidate all)
 *   ['admin-users', 'list', page, pageSize, status] ← paginated users list
 *   ['admin-users', 'detail', id]                   ← single user detail
 *   ['admin-users', 'invitations']                  ← pending invitations
 *
 * Invalidating `usersKeys.all` covers every sub-key via TanStack Query's
 * prefix-match behaviour.
 */
export const usersKeys = {
  all: ['admin-users'] as const,
  list: (page: number, pageSize: number, status: UserStatusFilter) =>
    [...usersKeys.all, 'list', page, pageSize, status] as const,
  detail: (id: string) => [...usersKeys.all, 'detail', id] as const,
  invitations: () => [...usersKeys.all, 'invitations'] as const,
}

const ANALYTICS_KEY = ['admin', 'analytics'] as const

export function useUsersList({ page = 1, pageSize = 50, status = 'all' }: ListUsersParams = {}) {
  return useQuery({
    queryKey: usersKeys.list(page, pageSize, status),
    queryFn: () => listUsersApi({ page, pageSize, status }),
    staleTime: 15_000,
  })
}

export function useInviteUser() {
  const qc = useQueryClient()
  return useMutation<void, Error, InviteUserRequest>({
    mutationFn: inviteUserApi,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: usersKeys.all })
      qc.invalidateQueries({ queryKey: usersKeys.invitations() })
      qc.invalidateQueries({ queryKey: ANALYTICS_KEY })
    },
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: usersKeys.all })
      qc.invalidateQueries({ queryKey: ANALYTICS_KEY })
    },
  })
}

export function useDeactivateUser() {
  const qc = useQueryClient()
  return useMutation<void, Error, string>({
    mutationFn: deactivateUserApi,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: usersKeys.all })
      qc.invalidateQueries({ queryKey: ANALYTICS_KEY })
    },
  })
}

export function useReactivateUser() {
  const qc = useQueryClient()
  return useMutation<Awaited<ReturnType<typeof reactivateUserApi>>, Error, string>({
    mutationFn: reactivateUserApi,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: usersKeys.all })
      qc.invalidateQueries({ queryKey: ANALYTICS_KEY })
    },
  })
}
