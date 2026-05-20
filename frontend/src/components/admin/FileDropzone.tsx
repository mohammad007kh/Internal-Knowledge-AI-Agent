'use client'

import { UploadCloudIcon } from 'lucide-react'
import { type ChangeEvent, type DragEvent, useCallback, useId, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

/**
 * Max bytes a single file may be before the dropzone rejects it.
 *
 * KEEP IN SYNC with the backend `upload_max_size_bytes` in
 * `backend/src/core/config.py` (currently 52_428_800 = 50 MiB). The presigned
 * upload flow also enforces this server-side; this is the friendly,
 * pre-upload guard so users don't watch a 200 MB file PUT for 30 s only to be
 * rejected.
 */
export const MAX_FILE_SIZE_BYTES = 52_428_800

/**
 * Accepted file extensions, lower-cased, no leading dot. Drives both the
 * extension gate and the hidden `<input accept="…">` string. Mirrors the file
 * source's accepted extensions — keep in sync with `detectFileType` /
 * `FILE_EXTENSION_MAP`.
 */
const ACCEPTED_EXTENSIONS: readonly string[] = ['pdf', 'docx', 'xlsx', 'csv', 'txt', 'md', 'markdown']

const ACCEPT_ATTR = ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(',')

/**
 * MIME allowlist — a frontend mirror of `_ALLOWED_CONTENT_TYPES` in
 * `backend/src/api/v1/sources.py`. Browsers are unreliable about file MIME
 * types (especially for `.md` / `.csv`, where they often hand back `''` or
 * `application/octet-stream`), so the MIME gate ACCEPTS a file whose MIME is
 * empty/octet-stream as long as its extension already passed.
 */
const ALLOWED_CONTENT_TYPES: ReadonlySet<string> = new Set([
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'text/csv',
  'text/plain',
  'text/markdown',
])

const AMBIGUOUS_MIME_TYPES: ReadonlySet<string> = new Set(['', 'application/octet-stream'])

const HIGHLIGHT_CLASSES = 'border-primary bg-primary/5'

function extensionOf(filename: string): string | null {
  const idx = filename.lastIndexOf('.')
  if (idx === -1 || idx === filename.length - 1) return null
  return filename.slice(idx + 1).toLowerCase()
}

interface RejectedFile {
  name: string
  reason: string
}

interface ValidationOutcome {
  accepted: File[]
  rejected: RejectedFile[]
}

/**
 * Per-file validation. Three gates, in order:
 *   1. extension — must be one of {@link ACCEPTED_EXTENSIONS}
 *      (folders fail here: their `File` has no extension)
 *   2. MIME — must be in {@link ALLOWED_CONTENT_TYPES}, OR empty/octet-stream
 *      with a passing extension
 *   3. size — must be ≤ {@link MAX_FILE_SIZE_BYTES}
 *
 * A mixed batch is partitioned: good files are accepted, bad ones are listed.
 */
function validateFiles(files: readonly File[]): ValidationOutcome {
  const accepted: File[] = []
  const rejected: RejectedFile[] = []

  for (const file of files) {
    const ext = extensionOf(file.name)
    if (ext === null || !ACCEPTED_EXTENSIONS.includes(ext)) {
      // A dropped folder surfaces as a `File` with empty type and (usually)
      // no extension — give it a folder-specific hint.
      const reason =
        ext === null && file.type === ''
          ? "folders aren't supported — drop individual files"
          : 'unsupported type'
      rejected.push({ name: file.name, reason })
      continue
    }

    const mime = file.type
    const mimeOk = ALLOWED_CONTENT_TYPES.has(mime) || AMBIGUOUS_MIME_TYPES.has(mime)
    if (!mimeOk) {
      rejected.push({ name: file.name, reason: 'PDF, DOCX, XLSX, CSV, TXT, or Markdown only' })
      continue
    }

    if (file.size > MAX_FILE_SIZE_BYTES) {
      rejected.push({ name: file.name, reason: 'too large (max 50 MB)' })
      continue
    }

    accepted.push(file)
  }

  return { accepted, rejected }
}

export interface FileDropzoneProps {
  /** Called with the files that passed all three validation gates. */
  onFiles: (files: File[]) => void
  /**
   * When true the dropzone is inert: the button is disabled, drag handlers
   * early-return, and an "Upload in progress…" hint is shown.
   */
  disabled?: boolean
  /**
   * `full` — generous padding + sub-line, used as the empty-state primary CTA.
   * `compact` — tighter, sub-line dropped, used as the "add more" affordance
   * above an existing file list.
   */
  variant?: 'full' | 'compact'
}

export function FileDropzone({ onFiles, disabled = false, variant = 'full' }: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const dragCounter = useRef(0)
  const [isDragging, setIsDragging] = useState(false)
  const [rejected, setRejected] = useState<readonly RejectedFile[]>([])
  const [addedCount, setAddedCount] = useState(0)
  const liveRegionId = useId()

  const handleFiles = useCallback(
    (fileList: FileList | null) => {
      const files = fileList ? Array.from(fileList) : []
      if (files.length === 0) return

      const { accepted, rejected: nextRejected } = validateFiles(files)
      // Always replace (never append): the rejection list reflects *this*
      // drop only, so repeated all-bad drops don't grow it unboundedly.
      // `addedCount` is the accepted count for this drop — 0 when the whole
      // drop was rejected, so the polite region doesn't announce a stale count.
      setRejected(nextRejected)
      setAddedCount(accepted.length)
      if (accepted.length > 0) onFiles(accepted)
    },
    [onFiles]
  )

  const openPicker = useCallback(() => {
    if (disabled) return
    inputRef.current?.click()
  }, [disabled])

  const onInputChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      handleFiles(event.target.files)
      // Reset so re-selecting the *same* file still fires `change`.
      event.target.value = ''
    },
    [handleFiles]
  )

  // `dragCounter` is ALWAYS kept accurate (enter ++ / leave --, clamped at 0)
  // regardless of `disabled`, so a zone that goes disabled mid-drag can't get
  // its counter poisoned. `isDragging` mirrors `dragCounter > 0`; the *visual*
  // highlight is additionally gated on `!disabled` where it's rendered.
  const onDragEnter = useCallback((event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault()
    dragCounter.current += 1
    setIsDragging(true)
  }, [])

  const onDragOver = useCallback((event: DragEvent<HTMLButtonElement>) => {
    // Intentionally no `disabled` guard: `preventDefault` here is REQUIRED for
    // the browser to fire `drop` at all (the `onDrop` handler does the
    // disabled bookkeeping).
    event.preventDefault()
  }, [])

  const onDragLeave = useCallback((event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault()
    // Always decrement (clamped) — counter bookkeeping must stay consistent
    // even if the zone became disabled while the cursor was over it.
    dragCounter.current = Math.max(0, dragCounter.current - 1)
    if (dragCounter.current === 0) setIsDragging(false)
  }, [])

  const onDrop = useCallback(
    (event: DragEvent<HTMLButtonElement>) => {
      // preventDefault even when disabled so the browser doesn't navigate to
      // the dropped file.
      event.preventDefault()
      dragCounter.current = 0
      setIsDragging(false)
      if (disabled) return
      handleFiles(event.dataTransfer.files)
    },
    [disabled, handleFiles]
  )

  const isFull = variant === 'full'
  const heading = isFull
    ? 'Drag & drop files here, or click to browse'
    : 'Drag more here or click to add'

  return (
    <div className="space-y-2">
      <button
        type="button"
        disabled={disabled}
        aria-disabled={disabled}
        aria-label="Upload files — drag and drop or press Enter to browse"
        aria-describedby={rejected.length > 0 ? liveRegionId : undefined}
        onClick={openPicker}
        onDragEnter={onDragEnter}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={cn(
          'flex w-full flex-col items-center justify-center gap-1.5 rounded-lg border-2 border-dashed border-input text-center transition-colors',
          'hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          isFull ? 'p-8' : 'p-4',
          isDragging && !disabled && HIGHLIGHT_CLASSES,
          disabled && 'pointer-events-none opacity-60'
        )}
      >
        <UploadCloudIcon className={cn('text-muted-foreground', isFull ? 'h-8 w-8' : 'h-5 w-5')} aria-hidden />
        <span className={cn('font-medium', isFull ? 'text-sm' : 'text-xs')}>{heading}</span>
        {isFull && (
          <span className="text-xs text-muted-foreground">
            PDF, Word, Excel, CSV, Text, or Markdown — up to 50 MB each.
          </span>
        )}
        {disabled && <span className="text-xs text-muted-foreground">Upload in progress…</span>}
      </button>

      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT_ATTR}
        className="sr-only"
        aria-hidden="true"
        tabIndex={-1}
        onChange={onInputChange}
      />

      {rejected.length > 0 && (
        <ul className="space-y-0.5 text-xs text-destructive">
          {rejected.map((entry) => (
            <li key={`${entry.name}-${entry.reason}`}>
              ✕ {entry.name} — {entry.reason}
            </li>
          ))}
        </ul>
      )}

      {/* Assertive: a rejection is something the user needs to act on. */}
      <div id={liveRegionId} className="sr-only" role="alert" aria-live="assertive">
        {rejected.length > 0
          ? `${rejected.length} file${rejected.length === 1 ? '' : 's'} rejected: ${rejected
              .map((r) => `${r.name} (${r.reason})`)
              .join(', ')}`
          : ''}
      </div>

      {/* Polite: a successful add is informational. */}
      <div className="sr-only" aria-live="polite">
        {addedCount > 0 ? `${addedCount} file${addedCount === 1 ? '' : 's'} added` : ''}
      </div>
    </div>
  )
}
