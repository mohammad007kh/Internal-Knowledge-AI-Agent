import { apiClient } from '@/lib/api-client'

export interface ConnectorResponse {
  id: string
  name: string
  connector_type: string
  is_active: boolean
  owner_id: string
  last_tested_at: string | null
  created_at: string
  updated_at: string
}

export interface PaginatedConnectors {
  items: ConnectorResponse[]
  total: number
}

export interface TestConnectorResponse {
  success: boolean
  message: string
}

export async function listConnectorsApi(page = 1, pageSize = 50): Promise<PaginatedConnectors> {
  const { data } = await apiClient.get<PaginatedConnectors>('/connectors', {
    params: { page, page_size: pageSize },
  })
  return data
}

export async function deleteConnectorApi(id: string): Promise<void> {
  await apiClient.delete<void>(`/connectors/${id}`)
}

export async function testConnectorApi(id: string): Promise<TestConnectorResponse> {
  const { data } = await apiClient.post<TestConnectorResponse>(`/connectors/${id}/test`, {})
  return data
}
