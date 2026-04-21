'use client'

import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
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
import { Textarea } from '@/components/ui/textarea'
import { apiClient } from '@/lib/api-client'

interface Connector {
  id: string
  name: string
  connector_type: string
}

interface ConnectorsResponse {
  items: Connector[]
  total: number
}

interface CreateSourceResponse {
  id: string
  name: string
}

const schema = z.object({
  name: z.string().min(1, 'Name is required').max(100),
  connector_id: z.string().uuid('Select a connector'),
  sync_schedule: z.enum(['manual', 'hourly', 'daily', 'weekly']),
  config_overrides: z.string().optional(),
})

type FormValues = z.infer<typeof schema>

async function fetchConnectors(): Promise<ConnectorsResponse> {
  const res = await apiClient.get<ConnectorsResponse>('/api/v1/connectors?limit=100')
  return res.data
}

async function createSource(values: FormValues): Promise<CreateSourceResponse> {
  const payload: Record<string, unknown> = {
    name: values.name,
    connector_id: values.connector_id,
    sync_schedule: values.sync_schedule,
  }
  if (values.config_overrides?.trim()) {
    payload.config_overrides = JSON.parse(values.config_overrides)
  }
  const res = await apiClient.post<CreateSourceResponse>('/api/v1/sources', payload)
  return res.data
}

export default function NewSourcePage() {
  const router = useRouter()

  const { data: connectorsData, isLoading: connectorsLoading } = useQuery({
    queryKey: ['connectors-all'],
    queryFn: fetchConnectors,
  })

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: '',
      connector_id: '',
      sync_schedule: 'manual',
      config_overrides: '',
    },
  })

  const mutation = useMutation({
    mutationFn: createSource,
    onSuccess: (data) => {
      toast.success('Source created')
      router.push(`/admin/sources/${data.id}`)
    },
    onError: () => toast.error('Failed to create source'),
  })

  function onSubmit(values: FormValues) {
    mutation.mutate(values)
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <div>
        <h1 className="text-2xl font-bold">New Source</h1>
        <p className="text-muted-foreground mt-1 text-sm">
          Connect a knowledge source to index documents.
        </p>
      </div>

      <Form {...form}>
        <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input placeholder="My Knowledge Base" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="connector_id"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Connector</FormLabel>
                <Select
                  disabled={connectorsLoading}
                  onValueChange={field.onChange}
                  value={field.value}
                >
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue placeholder="Select a connector…" />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {connectorsData?.items.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.name} — {c.connector_type}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="sync_schedule"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Sync Schedule</FormLabel>
                <Select onValueChange={field.onChange} value={field.value}>
                  <FormControl>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    <SelectItem value="manual">Manual</SelectItem>
                    <SelectItem value="hourly">Hourly</SelectItem>
                    <SelectItem value="daily">Daily</SelectItem>
                    <SelectItem value="weekly">Weekly</SelectItem>
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="config_overrides"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Config Overrides (JSON, optional)</FormLabel>
                <FormControl>
                  <Textarea className="font-mono text-xs" placeholder="{}" rows={4} {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <div className="flex gap-2 pt-2">
            <Button disabled={mutation.isPending} type="submit">
              {mutation.isPending ? 'Creating…' : 'Create Source'}
            </Button>
            <Button onClick={() => router.back()} type="button" variant="outline">
              Cancel
            </Button>
          </div>
        </form>
      </Form>
    </div>
  )
}
