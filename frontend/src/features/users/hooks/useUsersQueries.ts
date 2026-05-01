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

/**
 * Canonical query-key factory for all user / invitation / admin-users
 * related queries.
 *
 * Structure:
 *   ['admin-users']                                 ← root (invalidate all)
 *   ['admin-users', 'list', page, search]           ← paginated users list
 *   ['admin-users', 'list-legacy', limit, offset]   ← /api/v1/users listing
 *   ['admin-users', 'detail', id]                   ← single user detail
 *   ['admin-users', 'invitations']                  ← pending invitations
 *
 * Invalidating `usersKeys.all` covers every sub-key via TanStack Query's
 * prefix-match behaviour.
 */
export const usersKeys = {
  all: ['admin-users'] as const,
  list: (page: number, search: string) =>
    [...usersKeys.all, 'list', page, search] as const,
  listLegacy: (limit: number, offset: number) =>
    [...usersKeys.all, 'list-legacy', limit, offset] as const,
  detail: (id: string) => [...usersKeys.all, 'detail', id] as const,
  invitations: () => [...usersKeys.all, 'invitations'] as const,
}

const ANALYTICS_KEY = ['admin', 'analytics'] as const

export function useUsersList(limit = 50, offset = 0) {
  return useQuery({
    queryKey: usersKeys.listLegacy(limit, offset),
    queryFn: () => listUsersApi(limit, offset),
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
