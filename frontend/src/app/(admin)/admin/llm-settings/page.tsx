'use client'

import { EditStageDialog } from '@/app/(admin)/admin/llm-settings/_components/EditStageDialog'
import { StagesToolbar } from '@/app/(admin)/admin/llm-settings/_components/StagesToolbar'
import { useStageFilters } from '@/app/(admin)/admin/llm-settings/_components/useStageFilters'
import { ErrorState } from '@/components/ui/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useLlmSettings, useTestLlmStage } from '@/features/llm-settings/hooks/useLlmSettings'
import { useAiModels } from '@/hooks/use-ai-models'
import type { LlmStageConfig } from '@/lib/api/llm-settings'
import { getErrorMessage } from '@/lib/errors'
import { cn } from '@/lib/utils'
import { CheckCircle2Icon, CpuIcon, PencilIcon, PlusIcon, XCircleIcon, ZapIcon } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { toast } from 'sonner'

const EMPTY_STAGES: LlmStageConfig[] = []

const SKELETON_KEYS = ['s1', 's2', 's3', 's4', 's5', 's6'] as const

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
          setResult({ ok: true, text: `Connected (${data.latency_ms ?? '—'} ms)` })
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

  const aiModel = stage.ai_model

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div className="space-y-1 min-w-0 flex-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <CpuIcon className="h-4 w-4 text-muted-foreground" />
              <span className="flex-1">{stage.label}</span>
              {result ? (
                <span
                  className={cn(
                    'flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium',
                    result.ok
                      ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
                      : 'bg-destructive/10 text-destructive'
                  )}
                  title={result.text}
                >
                  {result.ok ? (
                    <CheckCircle2Icon className="h-3 w-3" />
                  ) : (
                    <XCircleIcon className="h-3 w-3" />
                  )}
                  {result.ok ? 'Healthy' : 'Error'}
                </span>
              ) : null}
            </CardTitle>
            <CardDescription className="text-xs">{stage.description}</CardDescription>
          </div>
          <Button
            size="icon"
            variant="outline"
            onClick={() => onEdit(stage)}
            aria-label={`Edit ${stage.label}`}
            className="h-9 w-9 shrink-0"
          >
            <PencilIcon className="h-4 w-4" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="flex items-center justify-between gap-2">
          <span className="shrink-0 text-muted-foreground">AI Model</span>
          {aiModel ? (
            <Link
              href={`/admin/ai-models?focus=${aiModel.id}`}
              className="inline-flex min-w-0 max-w-[60%] items-center gap-1.5 text-right hover:underline"
            >
              <Badge variant="secondary" className="shrink-0 text-[10px] uppercase tracking-wide">
                {aiModel.provider}
              </Badge>
              <span className="truncate font-medium">{aiModel.name}</span>
            </Link>
          ) : (
            <span className="text-xs italic text-muted-foreground">Not configured</span>
          )}
        </div>
        {aiModel ? (
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span className="shrink-0">Model ID</span>
            <span className="min-w-0 truncate font-mono" title={aiModel.model_id}>
              {aiModel.model_id}
            </span>
          </div>
        ) : null}
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Temperature</span>
          <span>
            {stage.temperature !== null ? (
              stage.temperature
            ) : (
              <span className="italic text-muted-foreground">Model default</span>
            )}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground">Max tokens</span>
          <span>
            {stage.max_tokens !== null ? (
              stage.max_tokens
            ) : (
              <span className="italic text-muted-foreground">Model default</span>
            )}
          </span>
        </div>
        <div className="pt-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={handleTest}
            disabled={testMutation.isPending || !aiModel}
            title={!aiModel ? 'Assign an AI model before testing' : undefined}
          >
            <ZapIcon className="mr-1.5 h-3.5 w-3.5" />
            {testMutation.isPending ? 'Testing…' : 'Test connection'}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function NoAiModelsCard() {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
        <CpuIcon className="h-10 w-10 text-muted-foreground" aria-hidden />
        <div className="space-y-1">
          <p className="text-base font-medium">No AI models configured yet</p>
          <p className="text-sm text-muted-foreground">
            Every stage needs one to run. Configure your first AI model to assign it across the
            pipeline.
          </p>
        </div>
        <Button asChild className="gap-1.5">
          <Link href="/admin/ai-models?new=1">
            <PlusIcon className="h-4 w-4" aria-hidden />
            Configure AI model
          </Link>
        </Button>
      </CardContent>
    </Card>
  )
}

export default function LlmSettingsPage() {
  const { data, isLoading, isError, error, refetch } = useLlmSettings()
  // Aggressively cached, but also surfaced here so the empty-state CTA can
  // appear before the user opens any dropdown.
  const { data: aiModels, isLoading: isLoadingAiModels } = useAiModels({ limit: 1 })
  const [editing, setEditing] = useState<LlmStageConfig | null>(null)

  const stages = data ?? EMPTY_STAGES
  const {
    state: filterState,
    setState: setFilterState,
    filteredStages,
    availableProviders,
    activeChips,
    clearAll,
    hasActiveFilters,
  } = useStageFilters(stages)

  const noAiModelsConfigured = !isLoadingAiModels && (aiModels?.total ?? 0) === 0

  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      <div>
        <h1 className="text-xl font-semibold">LLM Settings</h1>
        <p className="text-sm text-muted-foreground">
          Configure the AI Model and generation parameters for each pipeline stage.
        </p>
      </div>

      {noAiModelsConfigured ? <NoAiModelsCard /> : null}

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SKELETON_KEYS.map((key) => (
            <Skeleton key={key} className="h-56 w-full" />
          ))}
        </div>
      ) : null}

      {isError ? <ErrorState message={getErrorMessage(error)} onRetry={() => refetch()} /> : null}

      {data ? (
        <>
          <StagesToolbar
            state={filterState}
            onChange={setFilterState}
            availableProviders={availableProviders}
            activeChips={activeChips}
            onClearAll={clearAll}
            totalCount={stages.length}
            filteredCount={filteredStages.length}
          />

          {filteredStages.length === 0 ? (
            <Card className="border-dashed">
              <CardContent className="flex flex-col items-center gap-3 py-10 text-center">
                <p className="text-base font-medium">No stages match your filters.</p>
                {hasActiveFilters ? (
                  <button
                    type="button"
                    onClick={clearAll}
                    className="text-sm font-medium text-primary hover:underline"
                  >
                    Clear filters
                  </button>
                ) : null}
              </CardContent>
            </Card>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filteredStages.map((stage) => (
                <StageCard key={stage.stage} stage={stage} onEdit={setEditing} />
              ))}
            </div>
          )}
        </>
      ) : null}

      {editing ? (
        <EditStageDialog
          stage={editing}
          open={Boolean(editing)}
          onOpenChange={(open) => {
            if (!open) setEditing(null)
          }}
        />
      ) : null}
    </div>
  )
}
