'use client'

import { apiClient, parseErrorResponse } from '@/lib/api-client'
import { useMutation } from '@tanstack/react-query'
import axios from 'axios'

/**
 * Presigned upload flow:
 *   1. POST /api/v1/sources/upload-url → { upload_url, object_key }
 *   2. PUT file bytes directly to upload_url
 *   3. Caller uses object_key when creating the Source.
 *
 * Usage:
 *   const upload = useUploadFile()
 *   const { object_key } = await upload.mutateAsync({ file, onProgress })
 */

export interface UploadUrlRequest {
  filename: string
  content_type: string
}

export interface UploadUrlResponse {
  upload_url: string
  object_key: string
}

export interface UploadFileArgs {
  file: File
  onProgress?: (percent: number) => void
}

export interface UploadFileResult {
  object_key: string
}

async function requestUploadUrl(body: UploadUrlRequest): Promise<UploadUrlResponse> {
  const { data } = await apiClient.post<UploadUrlResponse>('/api/v1/sources/upload-url', body)
  return data
}

async function putToPresignedUrl(
  uploadUrl: string,
  file: File,
  onProgress?: (percent: number) => void
): Promise<void> {
  await axios.put(uploadUrl, file, {
    headers: {
      'Content-Type': file.type || 'application/octet-stream',
    },
    // Do not send cookies to the object store.
    withCredentials: false,
    onUploadProgress: (event) => {
      if (!onProgress || !event.total) return
      const percent = Math.round((event.loaded / event.total) * 100)
      onProgress(percent)
    },
  })
}

export function useUploadFile() {
  return useMutation<UploadFileResult, Error, UploadFileArgs>({
    mutationFn: async ({ file, onProgress }) => {
      try {
        const { upload_url, object_key } = await requestUploadUrl({
          filename: file.name,
          content_type: file.type || 'application/octet-stream',
        })
        await putToPresignedUrl(upload_url, file, onProgress)
        return { object_key }
      } catch (error: unknown) {
        throw parseErrorResponse(error)
      }
    },
  })
}
