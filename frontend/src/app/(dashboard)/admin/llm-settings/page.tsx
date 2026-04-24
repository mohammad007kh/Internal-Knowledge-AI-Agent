'use client'

import { EditStageDialog } from '@/app/(dashboard)/admin/llm-settings/_components/EditStageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton } from '@/components/ui/skeleton'
import { useLlmSettings, useTestLlmStage } from '@/features/llm-settings/hooks/useLlmSettings'
import { getErrorMessage } from '@/lib/errors'
import type { LlmStageConfig } from '@/lib/api/llm-settings'
import { CheckCircle2Icon, CpuIcon, PencilIcon, XCircleIcon, ZapIcon } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

function maskApiKey(hint: string | null): string {
  if (!hint) return 'Not configured'
  return `●●●●●●●● ${hint}`
}

interface StageCardProps {
  stage: LlmStageConfig
  onEdit: (stage: LlmStageConfig) => void
}

function StageCard({ stage, onEdit }: StageCardProps) {
  const testMutation = useTestLlmStage()
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null)

  function handleTest() {
    setResult(null)
    testMutation.mutate(stage.stage, {
      onSuccess: (data) => {
        if (data.success) {
          setResult({
            ok: true,
            text: `Connected (${data.latency_ms ?? '—'} ms)`,
          })
          toast.success(`${stage.label}: OK (${data.latency_ms ?? '—'} ms)`)
        } else {
          setResult({ ok: false, text: data.error ?? 'Connection failed' })
          toast.error(`${stage.label}: ${data.error ?? 'Connection failed'}`)
        }
      },
      onError: (err) => {
        setResult({ ok: false, text: getErrorMessage(err) })
        toast.error(`${stage.label}: ${getErrorMessage(err)}`)
      },
    })
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div className="space-y-1 min-w-0 flex-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <CpuIcon className="h-4 w-4 text-muted-foreground" />
              <span className="flex-1">{stage.label}</span>
              {result && (
                <span
                  className={
                    'flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium ' +
                    (result.ok
                      ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                      : 'bg-destructive/10 text-destructive')
                  }
                  title={result.text}
                >
                  {result.ok ? (
                    <CheckCircle2Icon className="h-3 w-3" />
                  ) : (
                    <XCircleIcon className="h-3 w-3" />
                  )}
                  {result.ok ? 'Healthy' : 'Error'}
                </span>
              )}
            </CardTitle>
            <CardDescription className="text-xs">{stage.description}</CardDescription>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => onEdit(stage)}
            aria-label={`Edit ${stage.label}`}
          >
            <PencilIcon className="h-3.5 w-3.5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Model</span>
          <Badge variant="secondary">{stage.model || 'default'}</Badge>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">API key</span>
          <span className="font-mono text-xs">{maskApiKey(stage.api_key_hint)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Temperature</span>
          <span>{stage.temperature}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Max tokens</span>
          <span>{stage.max_tokens}</span>
        </div>
        <div className="pt-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={handleTest}
            disabled={testMutation.isPending}
          >
            <ZapIcon className="mr-1.5 h-3.5 w-3.5" />
            {testMutation.isPending ? 'Testing…' : 'Test connection'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

export default function LlmSettingsPage() {
  const { data, isLoading, isError, error, refetch } = useLlmSettings()
  const [editing, setEditing] = useState<LlmStageConfig | null>(null)

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-xl font-semibold">LLM Settings</h1>
        <p className="text-sm text-muted-foreground">
          Configure model, API key, and generation parameters for each pipeline stage.
        </p>
      </div>

      {isLoading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-56 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <ErrorState message={getErrorMessage(error)} onRetry={() => refetch()} />
      )}

      {data && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.map((stage) => (
            <StageCard key={stage.stage} stage={stage} onEdit={setEditing} />
          ))}
        </div>
      )}

      {editing && (
        <EditStageDialog
          stage={editing}
          open={!!editing}
          onOpenChange={(open) => !open && setEditing(null)}
        />
      )}
    </div>
  )
}
