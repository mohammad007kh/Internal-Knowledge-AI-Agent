'use client'

import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useLlmSettings } from '@/features/llm-settings/hooks/useLlmSettings'
import type { LlmStageConfig } from '@/lib/api/llm-settings'
import Link from 'next/link'
import { ChartCard } from './ChartCard'

/**
 * LlmStagesPanel — compact table of the 10 pipeline LLM stages.
 *
 * Columns: stage · provider · model · temperature · custom prompt (✓/—).
 * Data from `useLlmSettings`. "Configure →" links to /admin/llm-settings.
 */

function modelLabel(stage: LlmStageConfig): string {
  return stage.ai_model?.model_id ?? stage.model ?? '—'
}

function providerLabel(stage: LlmStageConfig): string | null {
  return stage.ai_model?.provider ?? null
}

function tempLabel(stage: LlmStageConfig): string {
  return stage.temperature === null || stage.temperature === undefined
    ? 'inherit'
    : stage.temperature.toString()
}

function hasCustomPrompt(stage: LlmStageConfig): boolean {
  return !!stage.custom_prompt && stage.custom_prompt.trim().length > 0
}

export function LlmStagesPanel() {
  const { data, isLoading, isError } = useLlmSettings()
  const stages: LlmStageConfig[] = data ?? []

  return (
    <ChartCard
      title="LLM pipeline stages"
      actions={
        <Link href="/admin/llm-settings" className="text-xs font-medium text-primary hover:underline">
          Configure →
        </Link>
      }
      bodyClassName="p-0"
    >
      {isLoading ? (
        <div className="space-y-2 p-4">
          {['a', 'b', 'c', 'd', 'e'].map((k) => (
            <Skeleton key={k} className="h-8 w-full" />
          ))}
        </div>
      ) : isError ? (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground">Couldn&apos;t load LLM settings.</p>
      ) : stages.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground">No pipeline stages configured.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Stage</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead>Model</TableHead>
              <TableHead className="text-right">Temp</TableHead>
              <TableHead className="text-center">Custom prompt</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {stages.map((stage) => {
              const provider = providerLabel(stage)
              return (
                <TableRow key={stage.stage}>
                  <TableCell className="font-medium">{stage.label}</TableCell>
                  <TableCell>
                    {provider ? (
                      <Badge variant="secondary" className="text-[10px] uppercase">
                        {provider}
                      </Badge>
                    ) : (
                      <span className="text-xs italic text-muted-foreground">not configured</span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{modelLabel(stage)}</TableCell>
                  <TableCell className="text-right text-xs tabular-nums text-muted-foreground">
                    {tempLabel(stage)}
                  </TableCell>
                  <TableCell className="text-center text-xs">
                    {hasCustomPrompt(stage) ? (
                      <span className="text-emerald-600" aria-label="has custom prompt">
                        ✓
                      </span>
                    ) : (
                      <span className="text-muted-foreground" aria-label="no custom prompt">
                        —
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </ChartCard>
  )
}
