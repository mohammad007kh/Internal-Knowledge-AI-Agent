import { apiClient } from '@/lib/api-client'

export type UserRole = 'admin' | 'user'

/** Status filter accepted by `GET /api/v1/users` — `all` includes deactivated users. */
export type UserStatusFilter = 'all' | 'active' | 'inactive'

export interface UserListItem {
  id: string
  email: string
  full_name: string | null
  role: UserRole
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

/** `{items, total, page, page_size}` envelope returned by `GET /api/v1/users`. */
export interface UsersPage {
  items: UserListItem[]
  total: number
  page: number
  page_size: number
}

export interface ListUsersParams {
  page?: number
  pageSize?: number
  status?: UserStatusFilter
}

export interface InviteUserRequest {
  email: string
  role: UserRole
}

export interface ChangeRoleRequest {
  role: UserRole
}

export async function listUsersApi({
  page = 1,
  pageSize = 50,
  status = 'all',
}: ListUsersParams = {}): Promise<UsersPage> {
  const { data } = await apiClient.get<UsersPage>('/api/v1/users', {
    params: { page, page_size: pageSize, status },
  })
  return data
}

export async function inviteUserApi(body: InviteUserRequest): Promise<void> {
  await apiClient.post<void>('/api/v1/users/invitations', body)
}

export async function changeUserRoleApi(
  userId: string,
  body: ChangeRoleRequest
): Promise<UserListItem> {
  const { data } = await apiClient.patch<UserListItem>(`/api/v1/users/${userId}/role`, body)
  return data
}

export async function deactivateUserApi(userId: string): Promise<void> {
  await apiClient.delete<void>(`/api/v1/users/${userId}`)
}

export async function reactivateUserApi(userId: string): Promise<UserListItem> {
  const { data } = await apiClient.patch<UserListItem>(`/api/v1/users/${userId}`, {
    is_active: true,
  })
  return data
}

export async function getUserByIdApi(userId: string): Promise<UserListItem> {
  const { data } = await apiClient.get<UserListItem>(`/api/v1/users/${userId}`)
  return data
}
