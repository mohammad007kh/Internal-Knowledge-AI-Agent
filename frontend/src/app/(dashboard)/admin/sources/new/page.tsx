'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import {
  BookOpenIcon,
  ChevronRightIcon,
  CloudIcon,
  DatabaseIcon,
  FileIcon,
  FileTextIcon,
  GlobeIcon,
  TableIcon as TableColumnsIcon,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useCreateSource, type CreateSourcePayload } from '@/hooks/use-create-source'
import { useUploadFile } from '@/hooks/use-upload-url'
import { cn } from '@/lib/utils'

const SOURCE_TYPE_OPTIONS = [
  { value: 'pdf', label: 'PDF', icon: FileTextIcon, category: 'File' },
  { value: 'docx', label: 'Word', icon: FileTextIcon, category: 'File' },
  { value: 'xlsx', label: 'Excel', icon: TableColumnsIcon, category: 'File' },
  { value: 'csv', label: 'CSV', icon: FileIcon, category: 'File' },
  { value: 'txt', label: 'Text', icon: FileIcon, category: 'File' },
  { value: 'markdown', label: 'Markdown', icon: FileTextIcon, category: 'File' },
  { value: 'postgresql', label: 'PostgreSQL', icon: DatabaseIcon, category: 'Database' },
  { value: 'mysql', label: 'MySQL', icon: DatabaseIcon, category: 'Database' },
  { value: 'mssql', label: 'SQL Server', icon: DatabaseIcon, category: 'Database' },
  { value: 'mongodb', label: 'MongoDB', icon: DatabaseIcon, category: 'Database' },
  { value: 'web_url', label: 'Web URL', icon: GlobeIcon, category: 'Web' },
  { value: 'confluence', label: 'Confluence', icon: BookOpenIcon, category: 'SaaS' },
  { value: 'sharepoint', label: 'SharePoint', icon: CloudIcon, category: 'SaaS' },
] as const

const CRON_PRESETS = [
  { label: 'Hourly', value: '0 * * * *' },
  { label: 'Daily', value: '0 2 * * *' },
  { label: 'Weekly', value: '0 2 * * 1' },
] as const

const FILE_SOURCE_TYPES = new Set([
  'pdf', 'docx', 'xlsx', 'csv', 'txt', 'markdown',
])

const schema = z.object({
  source_type: z.enum([
    'postgresql', 'mysql', 'mssql', 'mongodb',
    'pdf', 'docx', 'xlsx', 'csv', 'txt', 'markdown',
    'web_url', 'confluence', 'sharepoint',
  ]),
  name: z.string().min(1, 'Name is required').max(200, 'Max 200 characters'),
  description: z.string().max(500, 'Max 500 characters').optional(),
  connection: z.string().optional(),
  retrieval_mode: z.enum(['vector_only', 'text_to_query', 'hybrid']),
  sync_mode: z.enum(['manual', 'scheduled', 'delta']),
  sync_schedule: z.string().optional(),
  citations_enabled: z.boolean(),
})

type FormValues = z.infer<typeof schema>

export default function NewSourcePage() {
  const router = useRouter()
  const createSource = useCreateSource()
  const uploadFile = useUploadFile()

  const [uploadProgress, setUploadProgress] = useState<number | null>(null)
  const [objectKey, setObjectKey] = useState<string | null>(null)
  const [uploadedFileName, setUploadedFileName] = useState<string | null>(null)

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      source_type: 'pdf',
      name: '',
      description: '',
      connection: '',
      retrieval_mode: 'hybrid',
      sync_mode: 'manual',
      sync_schedule: '',
      citations_enabled: true,
    },
  })

  const sourceType = form.watch('source_type')
  const syncMode = form.watch('sync_mode')
  const isFileType = FILE_SOURCE_TYPES.has(sourceType)

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    setUploadProgress(0)
    setObjectKey(null)

    try {
      const result = await uploadFile.mutateAsync({
        file,
        onProgress: setUploadProgress,
      })
      setObjectKey(result.object_key)
      setUploadedFileName(file.name)
      setUploadProgress(100)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Upload failed'
      toast.error(msg)
      setUploadProgress(null)
    }
  }

  async function onSubmit(values: FormValues) {
    if (isFileType && !objectKey) {
      toast.error('Please upload a file before submitting.')
      return
    }

    let connection: Record<string, unknown> | null = null
    if (!isFileType && values.connection?.trim()) {
      try {
        connection = JSON.parse(values.connection) as Record<string, unknown>
      } catch {
        form.setError('connection', { message: 'Invalid JSON — check the format.' })
        return
      }
    }

    const payload: CreateSourcePayload = {
      name: values.name,
      source_type: values.source_type as CreateSourcePayload['source_type'],
      description: values.description ?? '',
      connection,
      object_key: isFileType ? objectKey : null,
      retrieval_mode: values.retrieval_mode,
      sync_mode: values.sync_mode,
      sync_schedule:
        values.sync_mode === 'scheduled' ? (values.sync_schedule ?? null) : null,
      citations_enabled: values.citations_enabled,
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
    <div className="mx-auto max-w-2xl space-y-6 p-6">
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
        <h1 className="text-2xl font-bold">New Source</h1>
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
                        className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5"
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
                                setObjectKey(null)
                                setUploadedFileName(null)
                                setUploadProgress(null)
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

              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input placeholder="My Knowledge Base" maxLength={200} {...field} />
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
                        placeholder="What documents does this source contain?"
                        maxLength={500}
                        rows={2}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {isFileType ? 'File upload' : 'Connection'}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {isFileType ? (
                <div className="space-y-2">
                  <label className="block text-sm font-medium" htmlFor="file-upload">
                    Upload file
                  </label>
                  <input
                    id="file-upload"
                    type="file"
                    accept=".pdf,.docx,.xlsx,.csv,.txt,.md"
                    onChange={handleFileChange}
                    disabled={uploadFile.isPending}
                    className="block w-full text-sm text-muted-foreground file:mr-4 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground hover:file:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
                    aria-label="Upload file"
                  />
                  {uploadProgress !== null && uploadProgress < 100 && (
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full bg-primary transition-all"
                        style={{ width: `${uploadProgress}%` }}
                        role="progressbar"
                        aria-valuenow={uploadProgress}
                        aria-valuemin={0}
                        aria-valuemax={100}
                      />
                    </div>
                  )}
                  {uploadedFileName && (
                    <p className="text-xs text-muted-foreground">
                      Uploaded: <span className="font-medium">{uploadedFileName}</span>
                    </p>
                  )}
                </div>
              ) : (
                <FormField
                  control={form.control}
                  name="connection"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Connection config (JSON)</FormLabel>
                      <FormControl>
                        <Textarea
                          className="font-mono text-xs"
                          placeholder={'{\n  "host": "localhost",\n  "port": 5432\n}'}
                          rows={5}
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        Paste the connection details as valid JSON.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
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

          <div className="flex gap-3">
            <Button
              type="submit"
              disabled={createSource.isPending || uploadFile.isPending}
            >
              {createSource.isPending ? 'Creating…' : 'Create source'}
            </Button>
            <Button
              type="button"
              variant="outline"
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
