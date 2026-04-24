'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation } from '@tanstack/react-query'
import { EyeIcon, EyeOffIcon } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { forwardRef, useState, type ComponentPropsWithoutRef } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'

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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { apiClient } from '@/lib/api-client'

type PasswordInputProps = Omit<ComponentPropsWithoutRef<typeof Input>, 'type'> & {
  toggleLabel?: string
}

const PasswordInput = forwardRef<HTMLInputElement, PasswordInputProps>(
  ({ toggleLabel = 'secret', className, ...props }, ref) => {
    const [visible, setVisible] = useState(false)
    return (
      <div className="relative">
        <Input
          ref={ref}
          type={visible ? 'text' : 'password'}
          autoComplete="new-password"
          className={`pr-10 ${className ?? ''}`}
          {...props}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground transition-colors hover:text-foreground"
          aria-label={visible ? `Hide ${toggleLabel}` : `Show ${toggleLabel}`}
          tabIndex={-1}
        >
          {visible ? <EyeOffIcon className="h-4 w-4" /> : <EyeIcon className="h-4 w-4" />}
        </button>
      </div>
    )
  }
)
PasswordInput.displayName = 'PasswordInput'

// ─── Types ───────────────────────────────────────────────────────────────────

type ConnectorType = 'confluence' | 'jira' | 'sharepoint' | 'web' | 'file'

interface CreateConnectorResponse {
  id: string
}

// ─── Schema ──────────────────────────────────────────────────────────────────

const baseSchema = z.object({
  name: z.string().min(1, 'Name is required').max(100),
  connector_type: z.enum(['confluence', 'jira', 'sharepoint', 'web', 'file']),
})

const confluenceSchema = baseSchema.extend({
  connector_type: z.literal('confluence'),
  base_url: z.string().url('Enter a valid URL'),
  username: z.string().min(1, 'Username is required'),
  api_token: z.string().min(1, 'API token is required'),
  space_keys: z.string().min(1, 'Enter at least one space key'),
})

const jiraSchema = baseSchema.extend({
  connector_type: z.literal('jira'),
  base_url: z.string().url('Enter a valid URL'),
  username: z.string().min(1, 'Username is required'),
  api_token: z.string().min(1, 'API token is required'),
  project_keys: z.string().min(1, 'Enter at least one project key'),
})

const sharepointSchema = baseSchema.extend({
  connector_type: z.literal('sharepoint'),
  tenant_id: z.string().min(1, 'Tenant ID is required'),
  client_id: z.string().min(1, 'Client ID is required'),
  client_secret: z.string().min(1, 'Client secret is required'),
  site_url: z.string().url('Enter a valid URL'),
})

const webSchema = baseSchema.extend({
  connector_type: z.literal('web'),
  allowed_domains: z.string().min(1, 'Enter at least one domain'),
  crawl_depth: z.coerce.number().int().min(1).max(10),
  user_agent: z.string().optional(),
})

const fileSchema = baseSchema.extend({
  connector_type: z.literal('file'),
  allowed_extensions: z.string().min(1, 'Enter at least one extension'),
  max_file_size_mb: z.coerce.number().int().min(1).max(1000),
})

const schema = z.discriminatedUnion('connector_type', [
  confluenceSchema,
  jiraSchema,
  sharepointSchema,
  webSchema,
  fileSchema,
])

type FormValues = z.infer<typeof schema>

// ─── Type-specific field components ──────────────────────────────────────────

function ConfluenceFields({ form }: { form: ReturnType<typeof useForm<FormValues>> }) {
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
                placeholder="https://yourorg.atlassian.net"
                {...field}
                value={field.value ?? ''}
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
              <Input placeholder="you@example.com" {...field} value={field.value ?? ''} />
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
              <PasswordInput toggleLabel="API token" {...field} value={field.value ?? ''} />
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
              <Input placeholder="ENG, DOCS" {...field} value={field.value ?? ''} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  )
}

function JiraFields({ form }: { form: ReturnType<typeof useForm<FormValues>> }) {
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
                placeholder="https://yourorg.atlassian.net"
                {...field}
                value={field.value ?? ''}
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
              <Input placeholder="you@example.com" {...field} value={field.value ?? ''} />
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
              <PasswordInput toggleLabel="API token" {...field} value={field.value ?? ''} />
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
              <Input placeholder="PROJ, DEV" {...field} value={field.value ?? ''} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  )
}

function SharepointFields({ form }: { form: ReturnType<typeof useForm<FormValues>> }) {
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
                value={field.value ?? ''}
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
              <Input {...field} value={field.value ?? ''} />
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
              <PasswordInput toggleLabel="client secret" {...field} value={field.value ?? ''} />
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
                placeholder="https://yourorg.sharepoint.com/sites/..."
                {...field}
                value={field.value ?? ''}
              />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  )
}

function WebFields({ form }: { form: ReturnType<typeof useForm<FormValues>> }) {
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
                value={field.value ?? ''}
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
              <Input max={10} min={1} type="number" {...field} value={field.value ?? 3} />
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
              <Input placeholder="Mozilla/5.0 ..." {...field} value={field.value ?? ''} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  )
}

function FileFields({ form }: { form: ReturnType<typeof useForm<FormValues>> }) {
  return (
    <>
      <FormField
        control={form.control}
        name="allowed_extensions"
        render={({ field }) => (
          <FormItem>
            <FormLabel>Allowed Extensions</FormLabel>
            <FormControl>
              <Input placeholder=".pdf, .docx, .md" {...field} value={field.value ?? ''} />
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
              <Input max={1000} min={1} type="number" {...field} value={field.value ?? 50} />
            </FormControl>
            <FormMessage />
          </FormItem>
        )}
      />
    </>
  )
}

// ─── Page ────────────────────────────────────────────────────────────────────

const CONNECTOR_TYPES: { value: ConnectorType; label: string }[] = [
  { value: 'confluence', label: 'Confluence' },
  { value: 'jira', label: 'Jira' },
  { value: 'sharepoint', label: 'SharePoint' },
  { value: 'web', label: 'Web Crawler' },
  { value: 'file', label: 'File Upload' },
]

export default function NewConnectorPage() {
  const router = useRouter()
  const [selectedType, setSelectedType] = useState<ConnectorType | ''>('')

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '',
      connector_type: undefined,
    },
  })

  const mutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const res = await apiClient.post<CreateConnectorResponse>('/api/v1/connectors', values)
      return res.data
    },
    onSuccess: (data) => {
      toast.success('Connector created')
      router.push(`/admin/connectors/${data.id}`)
    },
    onError: () => {
      toast.error('Failed to create connector')
    },
  })

  function onSubmit(values: FormValues) {
    mutation.mutate(values)
  }

  function handleTypeChange(value: string) {
    setSelectedType(value as ConnectorType)
    form.setValue('connector_type', value as ConnectorType)
    form.clearErrors()
  }

  return (
    <div className="mx-auto max-w-lg space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold">Add Connector</h1>
        <p className="text-muted-foreground mt-1 text-sm">Configure a new data source connector.</p>
      </div>

      <Form {...form}>
        <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
          {/* Name */}
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Connector Name</FormLabel>
                <FormControl>
                  <Input placeholder="My Confluence" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* Connector type */}
          <FormItem>
            <FormLabel>Connector Type</FormLabel>
            <Select onValueChange={handleTypeChange} value={selectedType}>
              <FormControl>
                <SelectTrigger>
                  <SelectValue placeholder="Select a type" />
                </SelectTrigger>
              </FormControl>
              <SelectContent>
                {CONNECTOR_TYPES.map((ct) => (
                  <SelectItem key={ct.value} value={ct.value}>
                    {ct.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormItem>

          {/* Type-specific fields */}
          {selectedType === 'confluence' && <ConfluenceFields form={form} />}
          {selectedType === 'jira' && <JiraFields form={form} />}
          {selectedType === 'sharepoint' && <SharepointFields form={form} />}
          {selectedType === 'web' && <WebFields form={form} />}
          {selectedType === 'file' && <FileFields form={form} />}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <Button onClick={() => router.back()} type="button" variant="outline">
              Cancel
            </Button>
            <Button disabled={mutation.isPending || !selectedType} type="submit">
              {mutation.isPending ? 'Creating…' : 'Create Connector'}
            </Button>
          </div>
        </form>
      </Form>
    </div>
  )
}
