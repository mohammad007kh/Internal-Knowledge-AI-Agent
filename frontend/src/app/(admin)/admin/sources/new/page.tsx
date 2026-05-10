'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  ChevronRightIcon,
  DatabaseIcon,
  FileTextIcon,
  GlobeIcon,
  InfoIcon,
  Loader2Icon,
  PlusIcon,
  RefreshCwIcon,
  SparklesIcon,
  XIcon,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { type UseFormReturn, useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { EmbedderPicker } from '@/components/admin/EmbedderPicker'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  type CreateSourcePayload,
  type FileTypeKey,
  type UploadedFileRef,
  useCreateSource,
} from '@/hooks/use-create-source'
import { useUploadFile } from '@/hooks/use-upload-url'
import { cn } from '@/lib/utils'

// TODO: re-add 'confluence' and 'sharepoint' once backend connectors ship (see docs/architecture-review-2026-04.md)
const SOURCE_TYPE_OPTIONS = [
  { value: 'file_upload', label: 'Files', icon: FileTextIcon, category: 'File' },
  { value: 'database', label: 'Database', icon: DatabaseIcon, category: 'Database' },
  { value: 'web_url', label: 'Web URL', icon: GlobeIcon, category: 'Web' },
] as const

// TODO: Re-add 'recursive' once WebUrlConnector implements BFS with SSRF guard + same-domain + page-cap. See architecture-review-2026-04.md.
const CRAWL_MODES = ['single'] as const
type CrawlMode = (typeof CRAWL_MODES)[number]

const CRAWL_MODE_DESCRIPTIONS: Record<CrawlMode, string> = {
  single: 'Fetch just this URL once.',
}

const FILE_EXTENSION_MAP: Record<string, FileTypeKey> = {
  pdf: 'pdf',
  docx: 'docx',
  xlsx: 'xlsx',
  csv: 'csv',
  txt: 'txt',
  md: 'markdown',
  markdown: 'markdown',
}

const ACCEPTED_FILE_EXTENSIONS = '.pdf,.docx,.xlsx,.csv,.txt,.md,.markdown'
const MAX_PARALLEL_UPLOADS = 3

const FILE_TYPE_LABELS: Record<FileTypeKey, string> = {
  pdf: 'PDF',
  docx: 'Word',
  xlsx: 'Excel',
  csv: 'CSV',
  txt: 'Text',
  markdown: 'Markdown',
}

const FILE_TYPE_PILL_CLASSES: Record<FileTypeKey, string> = {
  pdf: 'bg-red-500/10 text-red-700 dark:text-red-300 border-red-500/30',
  docx: 'bg-blue-500/10 text-blue-700 dark:text-blue-300 border-blue-500/30',
  xlsx: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
  csv: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/30',
  txt: 'bg-zinc-500/10 text-zinc-700 dark:text-zinc-300 border-zinc-500/30',
  markdown: 'bg-violet-500/10 text-violet-700 dark:text-violet-300 border-violet-500/30',
}

function detectFileType(filename: string): FileTypeKey | null {
  const idx = filename.lastIndexOf('.')
  if (idx === -1) return null
  const ext = filename.slice(idx + 1).toLowerCase()
  return FILE_EXTENSION_MAP[ext] ?? null
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} kB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

type UploadStatus = 'queued' | 'uploading' | 'uploaded' | 'failed'

interface UploadEntry {
  /** Stable client-side id used as the React key. */
  localId: string
  file: File
  fileType: FileTypeKey
  status: UploadStatus
  progress: number
  objectKey: string | null
  error: string | null
}

function makeLocalId(): string {
  return `f-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

const CRON_PRESETS = [
  { label: 'Hourly', value: '0 * * * *' },
  { label: 'Daily', value: '0 2 * * *' },
  { label: 'Weekly', value: '0 2 * * 1' },
] as const

const FILE_SOURCE_TYPES = new Set(['file_upload'])

const DB_TYPES = ['postgresql', 'mysql', 'mssql', 'mongodb'] as const
type DbType = (typeof DB_TYPES)[number]
const SQL_DB_TYPES: ReadonlySet<DbType> = new Set<DbType>(['postgresql', 'mysql', 'mssql'])

const DB_TYPE_LABELS: Record<DbType, string> = {
  postgresql: 'PostgreSQL',
  mysql: 'MySQL',
  mssql: 'SQL Server',
  mongodb: 'MongoDB',
}

const DB_DEFAULT_PORTS: Record<DbType, number> = {
  postgresql: 5432,
  mysql: 3306,
  mssql: 1433,
  mongodb: 27017,
}

const DB_PREVIEW_SCHEME: Record<DbType, string> = {
  postgresql: 'postgresql',
  mysql: 'mysql',
  mssql: 'mssql',
  mongodb: 'mongodb',
}

const databaseConnectionSchema = z
  .object({
    db_type: z.enum(DB_TYPES),
    host: z.string().min(1, 'Host is required'),
    port: z.coerce.number().int().min(1, 'Port must be ≥ 1').max(65535, 'Port must be ≤ 65535'),
    database_name: z.string().min(1, 'Database name is required'),
    username: z.string().optional(),
    password: z.string().optional(),
    query: z.string().optional(),
    collection: z.string().optional(),
    ssl_mode: z.enum(['disable', 'require']).optional(),
  })
  .superRefine((value, ctx) => {
    if (value.db_type === 'mongodb') {
      if (!value.collection || value.collection.trim() === '') {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['collection'],
          message: 'Collection is required for MongoDB',
        })
      }
      return
    }
    if (!value.query || value.query.trim() === '') {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['query'],
        message: 'Query is required for SQL sources',
      })
    }
  })

type DatabaseConnectionValues = z.infer<typeof databaseConnectionSchema>

const webUrlSchema = z.object({
  url: z
    .string()
    .min(1, 'URL is required')
    .url('Enter a valid URL')
    .refine((value) => /^https?:\/\//i.test(value), {
      message: 'URL must start with http:// or https://',
    }),
  crawl_mode: z.enum(CRAWL_MODES),
})

const schema = z
  .object({
    // TODO: re-add when backend connectors ship — see docs/architecture-review-2026-04.md
    source_type: z.enum(['database', 'file_upload', 'web_url']),
    // F9: Name is conditionally required — see superRefine below. It is
    // optional at the schema level so the form remains valid when the user
    // opts into AI-naming and submits an empty string.
    name: z.string().max(200, 'Max 200 characters'),
    description: z.string().max(500, 'Max 500 characters').optional(),
    auto_name_and_description: z.boolean(),
    db_type: z.enum(DB_TYPES).optional(),
    host: z.string().optional(),
    port: z.union([z.string(), z.number()]).optional(),
    database_name: z.string().optional(),
    username: z.string().optional(),
    password: z.string().optional(),
    query: z.string().optional(),
    collection: z.string().optional(),
    ssl_mode: z.enum(['disable', 'require']).optional(),
    url: z.string().optional(),
    crawl_mode: z.enum(CRAWL_MODES).optional(),
    retrieval_mode: z.enum(['vector_only', 'text_to_query', 'hybrid']),
    sync_mode: z.enum(['manual', 'scheduled', 'delta']),
    sync_schedule: z.string().optional(),
    citations_enabled: z.boolean(),
  })
  .superRefine((values, ctx) => {
    // F9: Name is required only when the user has NOT opted into AI-naming.
    if (!values.auto_name_and_description && values.name.trim().length === 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: ['name'],
        message: 'Name is required',
      })
    }
    if (values.source_type === 'database') {
      const dbResult = databaseConnectionSchema.safeParse({
        db_type: values.db_type,
        host: values.host,
        port: values.port,
        database_name: values.database_name,
        username: values.username,
        password: values.password,
        query: values.query,
        collection: values.collection,
        ssl_mode: values.ssl_mode,
      })
      if (!dbResult.success) {
        for (const issue of dbResult.error.issues) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: issue.path,
            message: issue.message,
          })
        }
      }
      return
    }
    if (values.source_type === 'web_url') {
      const webResult = webUrlSchema.safeParse({
        url: values.url,
        crawl_mode: values.crawl_mode,
      })
      if (!webResult.success) {
        for (const issue of webResult.error.issues) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: issue.path,
            message: issue.message,
          })
        }
      }
    }
  })

type FormValues = z.infer<typeof schema>

function buildConnectionPreview(values: DatabaseConnectionValues): string {
  const scheme = DB_PREVIEW_SCHEME[values.db_type]
  const userPart = values.username ? `${values.username}:***@` : ''
  return `${scheme}://${userPart}${values.host || 'host'}:${values.port || DB_DEFAULT_PORTS[values.db_type]}/${values.database_name || 'dbname'}`
}

export default function NewSourcePage() {
  const router = useRouter()
  const createSource = useCreateSource()
  const uploadFile = useUploadFile()

  const [uploads, setUploads] = useState<UploadEntry[]>([])
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // Counters derived from uploads state.
  const uploadSummary = useMemo(() => {
    const total = uploads.length
    const uploaded = uploads.filter((u) => u.status === 'uploaded').length
    const failed = uploads.filter((u) => u.status === 'failed').length
    const inFlight = uploads.filter((u) => u.status === 'uploading' || u.status === 'queued').length
    return { total, uploaded, failed, inFlight }
  }, [uploads])

  const resetUploads = useCallback(() => {
    setUploads([])
  }, [])

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      source_type: 'file_upload',
      name: '',
      description: '',
      auto_name_and_description: false,
      db_type: 'postgresql',
      host: '',
      port: DB_DEFAULT_PORTS.postgresql,
      database_name: '',
      username: '',
      password: '',
      query: '',
      collection: '',
      ssl_mode: 'disable',
      url: '',
      crawl_mode: 'single',
      retrieval_mode: 'hybrid',
      sync_mode: 'manual',
      sync_schedule: '',
      citations_enabled: true,
    },
  })

  const sourceType = form.watch('source_type')
  const syncMode = form.watch('sync_mode')
  const dbType = form.watch('db_type') ?? 'postgresql'
  const autoNaming = form.watch('auto_name_and_description')
  const isFileType = FILE_SOURCE_TYPES.has(sourceType)
  const isDatabaseType = sourceType === 'database'
  const isMongo = isDatabaseType && dbType === 'mongodb'
  const isSqlDb = isDatabaseType && SQL_DB_TYPES.has(dbType)

  // Track whether the user has manually edited the port — only auto-fill when untouched.
  const portTouchedRef = useRef(false)

  useEffect(() => {
    if (!isDatabaseType) return
    if (portTouchedRef.current) return
    form.setValue('port', DB_DEFAULT_PORTS[dbType], { shouldDirty: false, shouldValidate: false })
  }, [dbType, isDatabaseType, form])

  const updateEntry = useCallback((localId: string, patch: Partial<UploadEntry>) => {
    setUploads((prev) =>
      prev.map((entry) => (entry.localId === localId ? { ...entry, ...patch } : entry))
    )
  }, [])

  const runUpload = useCallback(
    async (entry: UploadEntry) => {
      updateEntry(entry.localId, { status: 'uploading', progress: 0, error: null })
      try {
        const result = await uploadFile.mutateAsync({
          file: entry.file,
          onProgress: (percent) => {
            updateEntry(entry.localId, { progress: percent })
          },
        })
        updateEntry(entry.localId, {
          status: 'uploaded',
          progress: 100,
          objectKey: result.object_key,
          error: null,
        })
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Upload failed'
        updateEntry(entry.localId, {
          status: 'failed',
          error: msg,
        })
      }
    },
    [uploadFile, updateEntry]
  )

  /**
   * Concurrency-limited uploader: never run more than MAX_PARALLEL_UPLOADS at
   * a time.  Newly added entries are drained against the limit; the rest stay
   * 'queued' until a slot frees up.
   */
  const drainQueue = useCallback(
    async (newlyAdded: UploadEntry[]) => {
      let cursor = 0
      const inflight = new Set<Promise<void>>()
      const next = (): UploadEntry | undefined => newlyAdded[cursor++]

      const launch = (entry: UploadEntry): Promise<void> => {
        const task = runUpload(entry).finally(() => {
          inflight.delete(task)
        })
        inflight.add(task)
        return task
      }

      const initial = Math.min(MAX_PARALLEL_UPLOADS, newlyAdded.length)
      for (let i = 0; i < initial; i += 1) {
        const entry = next()
        if (entry) launch(entry)
      }

      while (inflight.size > 0) {
        await Promise.race(inflight)
        const entry = next()
        if (entry) launch(entry)
      }
    },
    [runUpload]
  )

  const enqueueFiles = useCallback(
    (files: FileList | File[]) => {
      const newEntries: UploadEntry[] = []
      const rejected: string[] = []

      for (const file of Array.from(files)) {
        const fileType = detectFileType(file.name)
        if (!fileType) {
          rejected.push(file.name)
          continue
        }
        newEntries.push({
          localId: makeLocalId(),
          file,
          fileType,
          status: 'queued',
          progress: 0,
          objectKey: null,
          error: null,
        })
      }

      if (rejected.length > 0) {
        toast.error(
          `Unsupported file type: ${rejected.join(', ')}. Allowed: PDF, Word, Excel, CSV, Text, Markdown.`
        )
      }
      if (newEntries.length === 0) return

      setUploads((prev) => [...prev, ...newEntries])
      void drainQueue(newEntries)
    },
    [drainQueue]
  )

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const list = e.target.files
    if (!list || list.length === 0) return
    enqueueFiles(list)
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function handleRetry(localId: string) {
    const entry = uploads.find((u) => u.localId === localId)
    if (!entry) return
    void runUpload({ ...entry, status: 'queued', progress: 0, error: null })
  }

  function handleRemove(localId: string) {
    setUploads((prev) => prev.filter((u) => u.localId !== localId))
  }

  function handleAddMore() {
    fileInputRef.current?.click()
  }

  async function onSubmit(values: FormValues) {
    if (isFileType) {
      if (uploadSummary.uploaded === 0) {
        toast.error('Upload at least one file before creating the source.')
        return
      }
      if (uploadSummary.inFlight > 0) {
        toast.error('Wait for in-progress uploads to finish.')
        return
      }
    }

    let connection: Record<string, unknown> | null = null
    if (values.source_type === 'database') {
      const portValue =
        typeof values.port === 'number' ? values.port : Number(values.port ?? Number.NaN)
      const dbTypeValue = values.db_type ?? 'postgresql'
      const base: Record<string, unknown> = {
        db_type: dbTypeValue,
        host: values.host ?? '',
        port: Number.isFinite(portValue) ? portValue : DB_DEFAULT_PORTS[dbTypeValue],
        database: values.database_name ?? '',
        username: values.username ?? '',
        password: values.password ?? '',
      }
      if (dbTypeValue === 'mongodb') {
        base.collection = values.collection ?? ''
      } else {
        base.query = values.query ?? ''
        if (values.ssl_mode) {
          base.ssl_mode = values.ssl_mode
        }
      }
      connection = base
    } else if (values.source_type === 'web_url') {
      connection = {
        url: values.url ?? '',
        crawl_mode: values.crawl_mode ?? 'single',
      }
    }

    let files: UploadedFileRef[] | null = null
    if (isFileType) {
      files = uploads
        .filter((u) => u.status === 'uploaded' && u.objectKey)
        .map((u) => ({
          object_key: u.objectKey as string,
          original_name: u.file.name,
          file_type: u.fileType,
          size_bytes: u.file.size,
        }))
    }

    // F9: when auto-naming is on, send empty strings for name + description
    // and let the backend stamp the placeholder. Otherwise pass the user's
    // values through unchanged.
    const payload: CreateSourcePayload = {
      name: values.auto_name_and_description ? '' : values.name,
      source_type: values.source_type,
      description: values.auto_name_and_description ? '' : (values.description ?? ''),
      connection,
      files,
      retrieval_mode: values.retrieval_mode,
      sync_mode: values.sync_mode,
      sync_schedule: values.sync_mode === 'scheduled' ? (values.sync_schedule ?? null) : null,
      citations_enabled: values.citations_enabled,
      auto_name_and_description: values.auto_name_and_description,
    }

    createSource.mutate(payload, {
      onSuccess: (result) => {
        toast.success('Source created successfully')
        router.push(`/admin/sources/${result.id}`)
      },
      onError: (err) => {
        toast.error(err.message || 'Failed to create source')
      },
    })
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-4 md:space-y-6 md:p-6">
      <nav
        className="flex items-center gap-1 text-sm text-muted-foreground"
        aria-label="Breadcrumb"
      >
        <Link href="/admin/sources" className="hover:text-foreground hover:underline">
          Sources
        </Link>
        <ChevronRightIcon className="h-4 w-4" aria-hidden />
        <span className="font-medium text-foreground">New Source</span>
      </nav>
      <div>
        <h1 className="text-xl font-bold md:text-2xl">New Source</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Connect a knowledge source to index documents for AI retrieval.
        </p>
      </div>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Source details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <FormField
                control={form.control}
                name="source_type"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Source type</FormLabel>
                    <FormControl>
                      <div
                        role="radiogroup"
                        aria-label="Source type"
                        className="grid grid-cols-2 gap-2 sm:grid-cols-3"
                      >
                        {SOURCE_TYPE_OPTIONS.map((opt) => {
                          const Icon = opt.icon
                          const checked = field.value === opt.value
                          return (
                            <button
                              key={opt.value}
                              type="button"
                              role="radio"
                              aria-checked={checked}
                              onClick={() => {
                                field.onChange(opt.value)
                                resetUploads()
                                if (opt.value === 'database') {
                                  portTouchedRef.current = false
                                  const currentDbType = form.getValues('db_type') ?? 'postgresql'
                                  form.setValue('port', DB_DEFAULT_PORTS[currentDbType], {
                                    shouldDirty: false,
                                    shouldValidate: false,
                                  })
                                }
                              }}
                              className={cn(
                                'flex flex-col items-center gap-1.5 rounded-lg border p-3 text-xs transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                                checked
                                  ? 'border-primary bg-primary/5 font-medium text-primary'
                                  : 'border-border text-muted-foreground'
                              )}
                            >
                              <Icon className="h-5 w-5" aria-hidden />
                              <span>{opt.label}</span>
                            </button>
                          )
                        })}
                      </div>
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">{isFileType ? 'Files' : 'Connection'}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {isFileType ? (
                <FilesPickerSection
                  uploads={uploads}
                  summary={uploadSummary}
                  fileInputRef={fileInputRef}
                  onPick={handleFileChange}
                  onAddMore={handleAddMore}
                  onRetry={handleRetry}
                  onRemove={handleRemove}
                />
              ) : isDatabaseType ? (
                <DatabaseConnectionFields
                  form={form}
                  isMongo={isMongo}
                  isSqlDb={isSqlDb}
                  onPortTouched={() => {
                    portTouchedRef.current = true
                  }}
                />
              ) : sourceType === 'web_url' ? (
                <WebUrlConnectionFields form={form} />
              ) : (
                <p className="text-sm text-muted-foreground">
                  No additional configuration is required for this source type yet.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Embedder</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="source-embedder">Embedder</Label>
                <EmbedderPicker
                  id="source-embedder"
                  value={null}
                  locked
                  // v1: locked to the active embedder. The picker renders the
                  // active embedder read-only and surfaces a link to
                  // /admin/embedders. The backend defaults `embedder_id` to
                  // the active embedder when omitted from the create
                  // payload, so we don't need to wire a controlled value
                  // through the form here.
                  onChange={() => {
                    /* locked — no-op */
                  }}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Retrieval &amp; sync</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <FormField
                control={form.control}
                name="retrieval_mode"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Retrieval mode</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="vector_only">Vector search</SelectItem>
                        <SelectItem value="text_to_query">Text to query</SelectItem>
                        <SelectItem value="hybrid">Hybrid</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="sync_mode"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Sync mode</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="manual">Manual</SelectItem>
                        <SelectItem value="scheduled">Scheduled</SelectItem>
                        <SelectItem value="delta">Delta</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {syncMode === 'scheduled' && (
                <FormField
                  control={form.control}
                  name="sync_schedule"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Cron schedule</FormLabel>
                      <div className="mb-2 flex flex-wrap gap-1.5">
                        {CRON_PRESETS.map((p) => (
                          <button
                            key={p.label}
                            type="button"
                            onClick={() => field.onChange(p.value)}
                            className={cn(
                              'rounded-full border px-2.5 py-0.5 text-xs transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                              field.value === p.value && 'border-primary bg-primary/10 text-primary'
                            )}
                          >
                            {p.label}
                          </button>
                        ))}
                      </div>
                      <FormControl>
                        <Input placeholder="0 2 * * *" {...field} />
                      </FormControl>
                      <FormDescription>
                        Cron expression (UTC). Example: <code>0 2 * * *</code> = daily at 02:00 UTC.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}

              <FormField
                control={form.control}
                name="citations_enabled"
                render={({ field }) => (
                  <FormItem className="flex items-center justify-between rounded-lg border p-3">
                    <div className="space-y-0.5">
                      <FormLabel htmlFor="citations-switch" className="text-sm">
                        Enable citations
                      </FormLabel>
                      <FormDescription className="text-xs">
                        Include source references in assistant replies.
                      </FormDescription>
                    </div>
                    <FormControl>
                      <Switch
                        id="citations-switch"
                        checked={field.value}
                        onCheckedChange={field.onChange}
                      />
                    </FormControl>
                  </FormItem>
                )}
              />
            </CardContent>
          </Card>

          {/* F9: AI-naming opt-in card. Lives last in the form so the user
              has already supplied connection / files context before deciding
              whether to let the assistant pick a name + description. */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Naming</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <FormField
                control={form.control}
                name="auto_name_and_description"
                render={({ field }) => (
                  <FormItem className="space-y-2">
                    <div className="flex items-start gap-3">
                      <FormControl>
                        <Checkbox
                          id="auto-naming-checkbox"
                          checked={field.value}
                          onCheckedChange={(next) => {
                            field.onChange(next)
                            if (next) {
                              // Clear the user's drafts so unchecking later
                              // gives them a fresh slate to type into.
                              form.setValue('name', '', {
                                shouldDirty: false,
                                shouldValidate: false,
                              })
                              form.setValue('description', '', {
                                shouldDirty: false,
                                shouldValidate: false,
                              })
                            }
                          }}
                          className="mt-0.5"
                        />
                      </FormControl>
                      <div className="space-y-1">
                        <FormLabel
                          htmlFor="auto-naming-checkbox"
                          className="flex items-center gap-1.5 text-sm font-medium"
                        >
                          <SparklesIcon
                            className="h-3.5 w-3.5 text-muted-foreground"
                            aria-hidden
                          />
                          Let AI name and describe this source for me
                        </FormLabel>
                        <FormDescription className="text-xs">
                          Skip this and the assistant will read your source after ingestion and
                          write a clear name + retrieval-friendly description. You can edit either
                          later.
                        </FormDescription>
                      </div>
                    </div>
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input
                        placeholder={
                          autoNaming
                            ? 'AI will pick a name after ingestion'
                            : 'My Knowledge Base'
                        }
                        maxLength={200}
                        disabled={autoNaming}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description (optional)</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder={
                          autoNaming
                            ? 'AI will write a description after ingestion'
                            : 'What documents does this source contain?'
                        }
                        maxLength={500}
                        rows={2}
                        disabled={autoNaming}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </CardContent>
          </Card>

          <div className="flex flex-col gap-2 sm:flex-row sm:gap-3">
            <Button
              type="submit"
              className="w-full sm:w-auto"
              disabled={
                createSource.isPending ||
                (isFileType && (uploadSummary.inFlight > 0 || uploadSummary.uploaded === 0))
              }
            >
              {createSource.isPending ? 'Creating…' : 'Create source'}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="w-full sm:w-auto"
              onClick={() => router.push('/admin/sources')}
            >
              Cancel
            </Button>
          </div>
        </form>
      </Form>
    </div>
  )
}

interface DatabaseConnectionFieldsProps {
  form: UseFormReturn<FormValues>
  isMongo: boolean
  isSqlDb: boolean
  onPortTouched: () => void
}

function DatabaseConnectionFields({
  form,
  isMongo,
  isSqlDb,
  onPortTouched,
}: DatabaseConnectionFieldsProps) {
  const dbType = (form.watch('db_type') ?? 'postgresql') as DbType
  const host = form.watch('host') ?? ''
  const port = form.watch('port')
  const databaseName = form.watch('database_name') ?? ''
  const username = form.watch('username') ?? ''

  const previewPort =
    typeof port === 'number'
      ? port
      : Number.isFinite(Number(port))
        ? Number(port)
        : DB_DEFAULT_PORTS[dbType]

  const preview = buildConnectionPreview({
    db_type: dbType,
    host,
    port: previewPort,
    database_name: databaseName,
    username,
  })

  return (
    <div className="space-y-4">
      <FormField
        control={form.control}
        name="db_type"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Database type</FormLabel>
            <Select
              onValueChange={(value) => {
                field.onChange(value)
                onPortTouched()
                // Reset the touched flag from the parent so default port can re-apply.
                // The parent's effect re-runs on db_type change and overwrites port
                // unless the user has manually edited it.
              }}
              value={field.value ?? 'postgresql'}
            >
              <FormControl>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                {DB_TYPES.map((t) => (
                  <SelectItem key={t} value={t}>
                    {DB_TYPE_LABELS[t]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <FormMessage />
          </FormItem>
        )}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <FormField
          control={form.control}
          name="host"
          render={({ field }) => (
            <FormItem className="sm:col-span-2">
              <FormLabel>Host</FormLabel>
              <FormControl>
                <Input placeholder="db.internal.example.com" autoComplete="off" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="port"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Port</FormLabel>
              <FormControl>
                <Input
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={65535}
                  value={field.value ?? ''}
                  onChange={(e) => {
                    onPortTouched()
                    const raw = e.target.value
                    field.onChange(raw === '' ? '' : Number(raw))
                  }}
                  onBlur={field.onBlur}
                  name={field.name}
                  ref={field.ref}
                />
              </FormControl>
              <FormDescription className="text-xs">
                Default: {DB_DEFAULT_PORTS[dbType]}
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>

      <FormField
        control={form.control}
        name="database_name"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Database name</FormLabel>
            <FormControl>
              <Input placeholder="analytics" autoComplete="off" {...field} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField
          control={form.control}
          name="username"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Username (optional)</FormLabel>
              <FormControl>
                <Input placeholder="readonly_user" autoComplete="off" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <FormField
          control={form.control}
          name="password"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Password (optional)</FormLabel>
              <FormControl>
                <Input
                  type="password"
                  placeholder="••••••••"
                  autoComplete="new-password"
                  {...field}
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
      </div>

      {/* TODO: Add read-only enforcement once SqlDatabaseConnector applies SET TRANSACTION READ ONLY at connect-time. See architecture-review-2026-04.md. */}

      {isSqlDb && (
        <FormField
          control={form.control}
          name="ssl_mode"
          render={({ field }) => (
            <FormItem>
              <FormLabel>SSL mode</FormLabel>
              <Select onValueChange={field.onChange} value={field.value ?? 'disable'}>
                <FormControl>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                </FormControl>
                <SelectContent>
                  <SelectItem value="disable">Disable</SelectItem>
                  <SelectItem value="require">Require</SelectItem>
                </SelectContent>
              </Select>
              <FormMessage />
            </FormItem>
          )}
        />
      )}

      {isSqlDb && (
        <FormField
          control={form.control}
          name="query"
          render={({ field }) => (
            <FormItem>
              <div className="flex items-center gap-1.5">
                <FormLabel className="m-0">Query</FormLabel>
                <Popover>
                  <PopoverTrigger asChild>
                    <button
                      type="button"
                      aria-label="About the query field"
                      className="-m-2 inline-flex h-9 w-9 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <InfoIcon className="h-4 w-4" aria-hidden />
                    </button>
                  </PopoverTrigger>
                  <PopoverContent side="top" className="max-w-xs text-sm">
                    <p>
                      Paste a SELECT that returns the rows to index. Read-only is enforced
                      regardless: the agent rejects anything that isn&apos;t a single SELECT.
                    </p>
                    <p className="mt-2">
                      Use any joins, filters, or projections you need to narrow the index to the
                      relevant tables and columns.
                    </p>
                    <p className="mt-2 font-medium">Read-only is enforced regardless.</p>
                  </PopoverContent>
                </Popover>
              </div>
              <FormControl>
                <Textarea
                  className="font-mono text-xs"
                  rows={4}
                  placeholder="SELECT id, title, body, updated_at FROM articles"
                  {...field}
                />
              </FormControl>
              <FormDescription>
                Required. Paste a SELECT statement that returns the rows to index.
              </FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
      )}

      {isMongo && (
        <FormField
          control={form.control}
          name="collection"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Collection</FormLabel>
              <FormControl>
                <Input placeholder="articles" autoComplete="off" {...field} />
              </FormControl>
              <FormDescription>MongoDB collection to read documents from.</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
      )}

      <div className="rounded-md border bg-muted/30 p-3">
        <div className="text-xs font-medium text-muted-foreground">Connection preview</div>
        <code className="mt-1 block break-all font-mono text-xs">{preview}</code>
      </div>

      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex">
              <Button type="button" variant="outline" size="sm" disabled>
                Test connection
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent>Coming soon</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Web URL connection — single URL + crawl mode picker.
// ---------------------------------------------------------------------------

interface WebUrlConnectionFieldsProps {
  form: UseFormReturn<FormValues>
}

function WebUrlConnectionFields({ form }: WebUrlConnectionFieldsProps) {
  // Crawl mode is fixed to 'single' for now — the Select is omitted entirely.
  // See WebUrlConnectionFields TODO above (CRAWL_MODES) for re-add criteria.

  return (
    <div className="space-y-4">
      <FormField
        control={form.control}
        name="url"
        render={({ field }) => (
          <FormItem>
            <FormLabel>URL</FormLabel>
            <FormControl>
              <Input
                type="url"
                inputMode="url"
                placeholder="https://docs.example.com/handbook"
                autoComplete="off"
                spellCheck={false}
                {...field}
              />
            </FormControl>
            <FormDescription>
              Must start with <code>http://</code> or <code>https://</code>.{' '}
              {CRAWL_MODE_DESCRIPTIONS.single}
            </FormDescription>
            <FormMessage />
          </FormItem>
        )}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Files picker — multi-file upload UI for the consolidated "Files" source.
// ---------------------------------------------------------------------------

interface UploadSummaryShape {
  total: number
  uploaded: number
  failed: number
  inFlight: number
}

interface FilesPickerSectionProps {
  uploads: UploadEntry[]
  summary: UploadSummaryShape
  fileInputRef: React.MutableRefObject<HTMLInputElement | null>
  onPick: (e: React.ChangeEvent<HTMLInputElement>) => void
  onAddMore: () => void
  onRetry: (localId: string) => void
  onRemove: (localId: string) => void
}

function FilesPickerSection({
  uploads,
  summary,
  fileInputRef,
  onPick,
  onAddMore,
  onRetry,
  onRemove,
}: FilesPickerSectionProps) {
  return (
    <div className="space-y-3">
      {uploads.length === 0 ? (
        <div className="space-y-2">
          <label className="block text-sm font-medium" htmlFor="file-upload">
            Upload files
          </label>
          <input
            ref={fileInputRef}
            id="file-upload"
            type="file"
            multiple
            accept={ACCEPTED_FILE_EXTENSIONS}
            onChange={onPick}
            className="block w-full text-sm text-muted-foreground file:mr-4 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90"
            aria-label="Upload files"
          />
          <p className="text-xs text-muted-foreground">
            Select one or more files. Allowed: PDF, Word, Excel, CSV, Text, Markdown.
          </p>
        </div>
      ) : (
        <>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_FILE_EXTENSIONS}
            onChange={onPick}
            className="sr-only"
            aria-label="Add more files"
          />
          <UploadSummary summary={summary} />
          <ul className="space-y-2" aria-label="Selected files">
            {uploads.map((entry) => (
              <UploadRow key={entry.localId} entry={entry} onRetry={onRetry} onRemove={onRemove} />
            ))}
          </ul>
          <Button type="button" variant="outline" size="sm" onClick={onAddMore} className="gap-1.5">
            <PlusIcon className="h-4 w-4" aria-hidden />
            Add more files
          </Button>
        </>
      )}
    </div>
  )
}

function UploadSummary({ summary }: { summary: UploadSummaryShape }) {
  if (summary.total === 0) return null
  const head = `${summary.total} ${summary.total === 1 ? 'file' : 'files'} selected`
  const tail: string[] = []
  if (summary.uploaded > 0) tail.push(`${summary.uploaded} uploaded`)
  if (summary.inFlight > 0) tail.push(`${summary.inFlight} in progress`)
  if (summary.failed > 0) tail.push(`${summary.failed} failed`)
  return (
    <div className="rounded-md bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
      {head}
      {tail.length > 0 ? ` (${tail.join(', ')})` : ''}
    </div>
  )
}

interface UploadRowProps {
  entry: UploadEntry
  onRetry: (localId: string) => void
  onRemove: (localId: string) => void
}

function UploadRow({ entry, onRetry, onRemove }: UploadRowProps) {
  return (
    <li
      className={cn(
        'flex items-start gap-3 rounded-md border p-3',
        entry.status === 'failed'
          ? 'border-destructive/40 bg-destructive/5'
          : 'border-border bg-background'
      )}
    >
      <div className="mt-0.5 shrink-0">
        <UploadStatusIcon status={entry.status} />
      </div>
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium" title={entry.file.name}>
            {entry.file.name}
          </span>
          <span
            className={cn(
              'rounded-full border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide',
              FILE_TYPE_PILL_CLASSES[entry.fileType]
            )}
          >
            {FILE_TYPE_LABELS[entry.fileType]}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span>{formatFileSize(entry.file.size)}</span>
          <span aria-hidden>·</span>
          <UploadStatusLabel entry={entry} />
        </div>
        {entry.status === 'uploading' && (
          <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
            <div
              className="h-full bg-primary transition-all"
              style={{ width: `${entry.progress}%` }}
              role="progressbar"
              tabIndex={-1}
              aria-valuenow={entry.progress}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
        )}
        {entry.status === 'failed' && entry.error && (
          <p className="text-xs text-destructive">{entry.error}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {entry.status === 'failed' && (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="gap-1 text-xs"
            onClick={() => onRetry(entry.localId)}
          >
            <RefreshCwIcon className="h-3.5 w-3.5" aria-hidden />
            Retry
          </Button>
        )}
        <Button
          type="button"
          size="icon"
          variant="ghost"
          aria-label={`Remove ${entry.file.name}`}
          onClick={() => onRemove(entry.localId)}
        >
          <XIcon className="h-4 w-4" aria-hidden />
        </Button>
      </div>
    </li>
  )
}

function UploadStatusIcon({ status }: { status: UploadStatus }) {
  if (status === 'uploaded') {
    return <CheckCircle2Icon className="h-4 w-4 text-emerald-600" aria-hidden />
  }
  if (status === 'failed') {
    return <AlertCircleIcon className="h-4 w-4 text-destructive" aria-hidden />
  }
  return <Loader2Icon className="h-4 w-4 animate-spin text-muted-foreground" aria-hidden />
}

function UploadStatusLabel({ entry }: { entry: UploadEntry }) {
  if (entry.status === 'queued') return <span>Queued</span>
  if (entry.status === 'uploading') return <span>Uploading {entry.progress}%</span>
  if (entry.status === 'uploaded') {
    return <span className="text-emerald-700 dark:text-emerald-400">Uploaded</span>
  }
  return <span className="text-destructive">Failed</span>
}
