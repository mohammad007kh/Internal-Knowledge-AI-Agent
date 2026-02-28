import { apiClient } from '@/lib/api-client'

export type SourceType = 'confluence' | 'sharepoint' | 'google_drive' | 'notion'

export interface SourceListItem {
  id: string
  name: string
  source_type: SourceType
  is_active: boolean
  created_at: string
}

export interface PaginatedSources {
  items: SourceListItem[]
  total: number
  limit: number
  offset: number
}

export interface CreateSourceRequest {
  name: string
  source_type: SourceType
  config: Record<string, unknown>
}

export interface TestConnectionResponse {
  success: boolean
  message: string
}

export interface SourcePermissionsResponse {
  user_ids: string[]
}

export interface GrantPermissionRequest {
  user_id: string
}

export async function listSourcesApi(limit = 50, offset = 0): Promise<PaginatedSources> {
  const { data } = await apiClient.get<PaginatedSources>('/sources', {
    params: { limit, offset },
  })
  return data
}

export async function createSourceApi(body: CreateSourceRequest): Promise<SourceListItem> {
  const { data } = await apiClient.post<SourceListItem>('/sources', body)
  return data
}

export async function deleteSourceApi(sourceId: string): Promise<void> {
  await apiClient.delete<void>(`/sources/${sourceId}`)
}

export async function testConnectionApi(sourceId: string): Promise<TestConnectionResponse> {
  const { data } = await apiClient.post<TestConnectionResponse>(
    `/sources/${sourceId}/test-connection`
  )
  return data
}

export async function listSourcePermissionsApi(sourceId: string): Promise<string[]> {
  const { data } = await apiClient.get<SourcePermissionsResponse>(
    `/sources/${sourceId}/permissions`
  )
  return data.user_ids
}

export async function grantPermissionApi(sourceId: string, userId: string): Promise<void> {
  await apiClient.post<void>(`/sources/${sourceId}/permissions`, {
    user_id: userId,
  } satisfies GrantPermissionRequest)
}

export async function revokePermissionApi(sourceId: string, userId: string): Promise<void> {
  await apiClient.delete<void>(`/sources/${sourceId}/permissions/${userId}`)
}
