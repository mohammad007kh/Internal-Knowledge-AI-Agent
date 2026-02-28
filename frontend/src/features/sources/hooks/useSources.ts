'use client'

import {
  type CreateSourceRequest,
  createSourceApi,
  deleteSourceApi,
  listSourcesApi,
  testConnectionApi,
} from '@/lib/api/sources'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

const SOURCES_KEY = ['sources'] as const

export function useListSources() {
  return useQuery({
    queryKey: [...SOURCES_KEY],
    queryFn: () => listSourcesApi(),
  })
}

export function useCreateSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateSourceRequest) => createSourceApi(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SOURCES_KEY })
      toast.success('Source created successfully')
    },
    onError: () => {
      toast.error('Failed to create source')
    },
  })
}

export function useDeleteSource() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sourceId: string) => deleteSourceApi(sourceId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: SOURCES_KEY })
      toast.success('Source deleted')
    },
    onError: () => {
      toast.error('Failed to delete source')
    },
  })
}

export function useTestConnection() {
  return useMutation({
    mutationFn: (sourceId: string) => testConnectionApi(sourceId),
    onSuccess: (data) => {
      if (data.success) {
        toast.success(data.message || 'Connection successful')
      } else {
        toast.error(data.message || 'Connection failed')
      }
    },
    onError: () => {
      toast.error('Connection test failed')
    },
  })
}
