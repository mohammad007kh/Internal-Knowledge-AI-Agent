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

/**
 * Allowlist of origins the browser may PUT presigned-upload bytes to.
 *
 * Derived from the same NEXT_PUBLIC_* env vars that drive the rest of the
 * app, so shifting HOST_MINIO_API_PORT (or HOST_BACKEND_PORT) only requires
 * a frontend rebuild — no source edits.
 *
 *   - NEXT_PUBLIC_API_URL          → backend origin (defensive: presigned
 *                                    URLs normally point at MinIO, but this
 *                                    keeps the allowlist symmetric with the
 *                                    rest of the API surface)
 *   - NEXT_PUBLIC_MINIO_PUBLIC_URL → MinIO public origin (the actual target)
 *
 * Both are baked at build time by Next.js. Defaults match docker-compose
 * defaults so direct `next dev` against a stock stack still works.
 */
function safeOrigin(url: string | undefined): string | null {
  if (!url) return null
  try {
    return new URL(url).origin
  } catch {
    return null
  }
}

const ALLOWED_UPLOAD_ORIGINS: readonly string[] = Array.from(
  new Set(
    [
      safeOrigin(process.env.NEXT_PUBLIC_API_URL) ?? 'http://localhost:8000',
      safeOrigin(process.env.NEXT_PUBLIC_MINIO_PUBLIC_URL) ?? 'http://localhost:9000',
    ].filter((origin): origin is string => origin !== null)
  )
)

function validateUploadUrl(url: string): void {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    throw new Error('Invalid upload URL returned by server')
  }
  const origin = parsed.origin
  if (!ALLOWED_UPLOAD_ORIGINS.includes(origin)) {
    throw new Error(`Upload URL origin "${origin}" is not trusted`)
  }
}

async function putToPresignedUrl(
  uploadUrl: string,
  file: File,
  onProgress?: (percent: number) => void
): Promise<void> {
  validateUploadUrl(uploadUrl)
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
