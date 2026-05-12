'use client'

import { HealthCards } from '@/components/admin/HealthCards'
import {
  useAnalyticsOverview,
  useChatVolume,
  useFeedbackTrend,
  useNeedsAttention,
  useSchemaStudies,
  useSourceHealth,
  useSyncActivity,
} from '@/features/analytics/hooks/useAnalytics'
import { AnalyticsHeader } from './AnalyticsHeader'
import { ChatVolumeChart } from './ChatVolumeChart'
import { FeedbackTrendChart } from './FeedbackTrendChart'
import { KpiRow } from './KpiRow'
import { LlmStagesPanel } from './LlmStagesPanel'
import { NeedsAttentionPanel } from './NeedsAttentionPanel'
import { RecentActionsFeed } from './RecentActionsFeed'
import { SchemaStudiesPanel } from './SchemaStudiesPanel'
import { SourceHealthPanel } from './SourceHealthPanel'
import { SyncActivityChart } from './SyncActivityChart'
import { useAnalyticsRange } from './useAnalyticsRange'

/**
 * /admin/analytics — the redesigned dashboard.
 *
 * Layout (responsive — matches the prior page's `lg:grid-cols-2` idiom):
 *   HealthCards strip  →  AnalyticsHeader  →  KpiRow (6→3→2 up)
 *   →  2-col chart grid (ChatVolume + FeedbackTrend ; SyncActivity + SourceHealth)
 *   →  3-col row (RecentActions + NeedsAttention + SchemaStudies ; stack on mobile)
 *   →  LlmStagesPanel full-width.
 *
 * Time-series charts + the period-delta KPIs react to `range`; the snapshot
 * panels (source-health, schema, LLM stages, needs-attention) are point-in-time
 * and ignore it.
 */
export function AnalyticsDashboard() {
  const { range, setRange } = useAnalyticsRange()

  const overview = useAnalyticsOverview(range)
  const chatVolume = useChatVolume(range)
  const feedbackTrend = useFeedbackTrend(range)
  const syncActivity = useSyncActivity(range)
  const sourceHealth = useSourceHealth()
  const schemaStudies = useSchemaStudies()
  const needsAttention = useNeedsAttention()

  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      <HealthCards />

      <AnalyticsHeader range={range} onRangeChange={setRange} />

      <KpiRow
        overview={overview.data}
        chatVolume={chatVolume.data}
        loading={overview.isPending}
        rangeLabel={range}
      />

      <div className="grid gap-4 md:gap-6 lg:grid-cols-2">
        <ChatVolumeChart data={chatVolume.data} loading={chatVolume.isPending} />
        <FeedbackTrendChart data={feedbackTrend.data} loading={feedbackTrend.isPending} />
        <SyncActivityChart data={syncActivity.data} loading={syncActivity.isPending} />
        <SourceHealthPanel data={sourceHealth.data} loading={sourceHealth.isPending} />
      </div>

      <div className="grid gap-4 md:gap-6 lg:grid-cols-3">
        <RecentActionsFeed />
        <NeedsAttentionPanel data={needsAttention.data} loading={needsAttention.isPending} />
        <SchemaStudiesPanel data={schemaStudies.data} loading={schemaStudies.isPending} />
      </div>

      <LlmStagesPanel />
    </div>
  )
}
