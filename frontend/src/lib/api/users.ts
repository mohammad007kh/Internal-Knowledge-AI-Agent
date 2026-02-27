import { apiClient } from '@/lib/api-client'

export type UserRole = 'admin' | 'user'

export interface UserListItem {
  id: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface PaginatedUsers {
  items: UserListItem[]
  total: number
  limit: number
  offset: number
}

export interface InviteUserRequest {
  email: string
  role: UserRole
}

export interface ChangeRoleRequest {
  role: UserRole
}

export async function listUsersApi(limit = 50, offset = 0): Promise<PaginatedUsers> {
  const { data } = await apiClient.get<PaginatedUsers>('/users', {
    params: { limit, offset },
  })
  return data
}

export async function inviteUserApi(body: InviteUserRequest): Promise<void> {
  await apiClient.post<void>('/users/invitations', body)
}

export async function changeUserRoleApi(
  userId: string,
  body: ChangeRoleRequest
): Promise<UserListItem> {
  const { data } = await apiClient.patch<UserListItem>(`/users/${userId}/role`, body)
  return data
}

export async function deactivateUserApi(userId: string): Promise<void> {
  await apiClient.delete<void>(`/users/${userId}`)
}
