'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import * as z from 'zod'

import { Button } from '@/components/ui/button'
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { apiClient } from '@/lib/api-client'

// ─── Types ───────────────────────────────────────────────────────────────────

type ConnectorType = 'confluence' | 'jira' | 'sharepoint' | 'web' | 'file'

interface ConnectorDetail {
  id: string
  name: string
  connector_type: ConnectorType
  is_active: boolean
  source_count?: number
  last_tested_at?: string | null
  config?: Record<string, unknown>
}

// ─── Zod schemas (mirrors connectors/new) ────────────────────────────────────

const baseSchema = z.object({ name: z.string().min(1, 'Name is required') })

const confluenceEditSchema = baseSchema.extend({
  connector_type: z.literal('confluence'),
  base_url: z.string().url('Must be a valid URL'),
  username: z.string().min(1, 'Username is required'),
  api_token: z.string(), // optional on edit — empty = unchanged
  space_keys: z.string().min(1, 'At least one space key is required'),
})

const jiraEditSchema = baseSchema.extend({
  connector_type: z.literal('jira'),
  base_url: z.string().url('Must be a valid URL'),
  username: z.string().min(1, 'Username is required'),
  api_token: z.string(),
  project_keys: z.string().min(1, 'At least one project key is required'),
})

const sharepointEditSchema = baseSchema.extend({
  connector_type: z.literal('sharepoint'),
  tenant_id: z.string().min(1, 'Tenant ID is required'),
  client_id: z.string().min(1, 'Client ID is required'),
  client_secret: z.string(),
  site_url: z.string().url('Must be a valid URL'),
})

const webEditSchema = baseSchema.extend({
  connector_type: z.literal('web'),
  allowed_domains: z.string().min(1, 'At least one domain is required'),
  crawl_depth: z.coerce.number().int().min(1).max(10),
  user_agent: z.string().optional(),
})

const fileEditSchema = baseSchema.extend({
  connector_type: z.literal('file'),
  allowed_extensions: z.string().min(1, 'At least one file extension is required'),
  max_file_size_mb: z.coerce.number().int().min(1).max(1000),
})

const editConnectorSchema = z.discriminatedUnion('connector_type', [
  confluenceEditSchema,
  jiraEditSchema,
  sharepointEditSchema,
  webEditSchema,
  fileEditSchema,
])

type EditConnectorValues = z.infer<typeof editConnectorSchema>

// ─── Type-specific field sub-components ──────────────────────────────────────

function ConfluenceFields({ form }: { form: ReturnType<typeof useForm<EditConnectorValues>> }) {
  return (
    <>
      <FormField
        control={form.control}
        name="base_url"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Base URL</FormLabel>
            <FormControl>
              <Input
                placeholder="https://yourcompany.atlassian.net"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="username"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Username</FormLabel>
            <FormControl>
              <Input
                placeholder="user@example.com"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="api_token"
        render={({ field }) => (
          <FormItem>
            <FormLabel>API Token</FormLabel>
            <FormControl>
              <Input
                type="password"
                placeholder="Leave blank to keep existing token"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="space_keys"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Space Keys</FormLabel>
            <FormControl>
              <Input placeholder="KEY1, KEY2" {...field} value={(field.value as string) ?? ''} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  )
}

function JiraFields({ form }: { form: ReturnType<typeof useForm<EditConnectorValues>> }) {
  return (
    <>
      <FormField
        control={form.control}
        name="base_url"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Base URL</FormLabel>
            <FormControl>
              <Input
                placeholder="https://yourcompany.atlassian.net"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="username"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Username</FormLabel>
            <FormControl>
              <Input
                placeholder="user@example.com"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="api_token"
        render={({ field }) => (
          <FormItem>
            <FormLabel>API Token</FormLabel>
            <FormControl>
              <Input
                type="password"
                placeholder="Leave blank to keep existing token"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="project_keys"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Project Keys</FormLabel>
            <FormControl>
              <Input placeholder="PROJ1, PROJ2" {...field} value={(field.value as string) ?? ''} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  )
}

function SharepointFields({ form }: { form: ReturnType<typeof useForm<EditConnectorValues>> }) {
  return (
    <>
      <FormField
        control={form.control}
        name="tenant_id"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Tenant ID</FormLabel>
            <FormControl>
              <Input
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="client_id"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Client ID</FormLabel>
            <FormControl>
              <Input
                placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="client_secret"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Client Secret</FormLabel>
            <FormControl>
              <Input
                type="password"
                placeholder="Leave blank to keep existing secret"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="site_url"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Site URL</FormLabel>
            <FormControl>
              <Input
                placeholder="https://yourcompany.sharepoint.com/sites/mysite"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  )
}

function WebFields({ form }: { form: ReturnType<typeof useForm<EditConnectorValues>> }) {
  return (
    <>
      <FormField
        control={form.control}
        name="allowed_domains"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Allowed Domains</FormLabel>
            <FormControl>
              <Input
                placeholder="example.com, docs.example.com"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="crawl_depth"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Crawl Depth</FormLabel>
            <FormControl>
              <Input
                type="number"
                min={1}
                max={10}
                placeholder="3"
                {...field}
                value={(field.value as number) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="user_agent"
        render={({ field }) => (
          <FormItem>
            <FormLabel>User Agent (optional)</FormLabel>
            <FormControl>
              <Input
                placeholder="KnowledgeBot/1.0"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  )
}

function FileFields({ form }: { form: ReturnType<typeof useForm<EditConnectorValues>> }) {
  return (
    <>
      <FormField
        control={form.control}
        name="allowed_extensions"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Allowed Extensions</FormLabel>
            <FormControl>
              <Input
                placeholder=".pdf, .docx, .txt"
                {...field}
                value={(field.value as string) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
      <FormField
        control={form.control}
        name="max_file_size_mb"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Max File Size (MB)</FormLabel>
            <FormControl>
              <Input
                type="number"
                min={1}
                max={1000}
                placeholder="50"
                {...field}
                value={(field.value as number) ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  )
}

// ─── Page component ───────────────────────────────────────────────────────────

export default function ConnectorDetailPage() {
  const { id } = useParams<{ id: string }>()
  const router = useRouter()
  const queryClient = useQueryClient()
  const [formReady, setFormReady] = useState(false)

  const { data: connector, isLoading } = useQuery<ConnectorDetail>({
    queryKey: ['connector', id],
    queryFn: async () => {
      const res = await apiClient.get<ConnectorDetail>(`/api/v1/connectors/${id}`)
      return res.data
    },
    enabled: !!id,
  })

  const form = useForm<EditConnectorValues>({
    resolver: zodResolver(editConnectorSchema),
    defaultValues: {
      name: '',
      connector_type: 'confluence',
    } as EditConnectorValues,
  })

  // Pre-populate form once connector data loads
  useEffect(() => {
    if (!connector) return
    const cfg = (connector.config ?? {}) as Record<string, unknown>
    const shared = { name: connector.name, connector_type: connector.connector_type }

    if (connector.connector_type === 'confluence') {
      form.reset({
        ...shared,
        connector_type: 'confluence',
        base_url: (cfg.base_url as string) ?? '',
        username: (cfg.username as string) ?? '',
        api_token: '',
        space_keys: (cfg.space_keys as string) ?? '',
      })
    } else if (connector.connector_type === 'jira') {
      form.reset({
        ...shared,
        connector_type: 'jira',
        base_url: (cfg.base_url as string) ?? '',
        username: (cfg.username as string) ?? '',
        api_token: '',
        project_keys: (cfg.project_keys as string) ?? '',
      })
    } else if (connector.connector_type === 'sharepoint') {
      form.reset({
        ...shared,
        connector_type: 'sharepoint',
        tenant_id: (cfg.tenant_id as string) ?? '',
        client_id: (cfg.client_id as string) ?? '',
        client_secret: '',
        site_url: (cfg.site_url as string) ?? '',
      })
    } else if (connector.connector_type === 'web') {
      form.reset({
        ...shared,
        connector_type: 'web',
        allowed_domains: (cfg.allowed_domains as string) ?? '',
        crawl_depth: (cfg.crawl_depth as number) ?? 3,
        user_agent: (cfg.user_agent as string) ?? '',
      })
    } else if (connector.connector_type === 'file') {
      form.reset({
        ...shared,
        connector_type: 'file',
        allowed_extensions: (cfg.allowed_extensions as string) ?? '',
        max_file_size_mb: (cfg.max_file_size_mb as number) ?? 50,
      })
    }

    setFormReady(true)
  }, [connector, form])

  const saveMutation = useMutation({
    mutationFn: async (values: EditConnectorValues) => {
      const res = await apiClient.put<ConnectorDetail>(`/api/v1/connectors/${id}`, values)
      return res.data
    },
    onSuccess: () => {
      toast.success('Connector updated')
      queryClient.invalidateQueries({ queryKey: ['connector', id] })
      queryClient.invalidateQueries({ queryKey: ['connectors'] })
    },
    onError: () => {
      toast.error('Failed to update connector')
    },
  })

  const testMutation = useMutation({
    mutationFn: async () => {
      const res = await apiClient.post(`/api/v1/connectors/${id}/test`, {})
      return res.data
    },
    onSuccess: () => {
      toast.success('Connection test passed')
      queryClient.invalidateQueries({ queryKey: ['connector', id] })
    },
    onError: () => {
      toast.error('Connection test failed')
    },
  })

  function onSubmit(values: EditConnectorValues) {
    saveMutation.mutate(values)
  }

  if (isLoading) {
    return (
      <div className="space-y-4 p-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-32" />
        <div className="space-y-3">
          {['sk-f0', 'sk-f1', 'sk-f2', 'sk-f3'].map((skKey) => (
            <Skeleton key={skKey} className="h-10 w-full" />
          ))}
        </div>
      </div>
    )
  }

  if (!connector) {
    return (
      <div className="p-6">
        <p className="text-muted-foreground">Connector not found.</p>
        <Button asChild variant="link" className="mt-2 px-0">
          <Link href="/admin/connectors">Back to Connectors</Link>
        </Button>
      </div>
    )
  }

  const connectorType = connector.connector_type

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-4 md:space-y-6 md:p-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="break-words text-xl font-semibold md:text-2xl">{connector.name}</h1>
          <p className="text-muted-foreground mt-1 text-sm capitalize">{connectorType} connector</p>
        </div>
        <Button
          className="w-full sm:w-auto"
          variant="outline"
          onClick={() => testMutation.mutate()}
          disabled={testMutation.isPending}
        >
          {testMutation.isPending ? 'Testing…' : 'Test Connection'}
        </Button>
      </div>

      {/* Connector type label (read-only) */}
      <div className="space-y-1.5">
        <Label>Connector Type</Label>
        <Input value={connectorType} disabled className="capitalize" />
      </div>

      {/* Edit form */}
      {formReady && (
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            {/* Name */}
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input placeholder="My Connector" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Type-specific fields */}
            {connectorType === 'confluence' && <ConfluenceFields form={form} />}
            {connectorType === 'jira' && <JiraFields form={form} />}
            {connectorType === 'sharepoint' && <SharepointFields form={form} />}
            {connectorType === 'web' && <WebFields form={form} />}
            {connectorType === 'file' && <FileFields form={form} />}

            {/* Actions */}
            <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:gap-3">
              <Button
                type="button"
                variant="outline"
                className="w-full sm:w-auto"
                onClick={() => router.back()}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                className="w-full sm:w-auto"
                disabled={saveMutation.isPending}
              >
                {saveMutation.isPending ? 'Saving…' : 'Save Changes'}
              </Button>
            </div>
          </form>
        </Form>
      )}
    </div>
  )
}
