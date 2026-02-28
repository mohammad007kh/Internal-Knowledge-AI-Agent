'use client'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
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
import { useCreateSource } from '@/features/sources/hooks/useSources'
import { zodResolver } from '@hookform/resolvers/zod'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

const SOURCE_TYPES = ['confluence', 'sharepoint', 'google_drive', 'notion'] as const

const createSourceSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  source_type: z.enum(SOURCE_TYPES, { required_error: 'Source type is required' }),
  config: z
    .string()
    .min(1, 'Config is required')
    .refine((val) => {
      try {
        JSON.parse(val)
        return true
      } catch {
        return false
      }
    }, 'Config must be valid JSON'),
})

type CreateSourceFormValues = z.infer<typeof createSourceSchema>

export function CreateSourceDialog() {
  const [open, setOpen] = useState(false)
  const createMutation = useCreateSource()

  const form = useForm<CreateSourceFormValues>({
    resolver: zodResolver(createSourceSchema),
    defaultValues: {
      name: '',
      config: '{}',
    },
  })

  function onSubmit(values: CreateSourceFormValues) {
    createMutation.mutate(
      {
        name: values.name,
        source_type: values.source_type,
        config: JSON.parse(values.config) as Record<string, unknown>,
      },
      {
        onSuccess: () => {
          form.reset()
          setOpen(false)
        },
      }
    )
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          Add Source
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>Add Source</DialogTitle>
          <DialogDescription>
            Configure a new knowledge source to connect to the AI agent.
          </DialogDescription>
        </DialogHeader>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Name</FormLabel>
                  <FormControl>
                    <Input placeholder="My Confluence Space" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="source_type"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Source Type</FormLabel>
                  <Select onValueChange={field.onChange} defaultValue={field.value}>
                    <FormControl>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a source type" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {SOURCE_TYPES.map((type) => (
                        <SelectItem key={type} value={type}>
                          {type}
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
              name="config"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Config (JSON)</FormLabel>
                  <FormControl>
                    <Textarea
                      placeholder='{"base_url": "https://...", "api_key": "..."}'
                      className="font-mono text-sm"
                      rows={5}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? 'Creating…' : 'Create'}
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  )
}
