import { ActivityFeed } from '@/components/admin/ActivityFeed'
import { HealthCards } from '@/components/admin/HealthCards'
import { MetricsCards } from '@/components/admin/MetricsCards'
import { QueryVolumeChart } from '@/components/admin/QueryVolumeChart'
import { TopSourcesTable } from '@/components/admin/TopSourcesTable'
import type { Metadata } from 'next'
import { Suspense } from 'react'

export const metadata: Metadata = {
  title: 'Dashboard — Admin',
}

export default function AdminPage() {
  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      <h1 className="text-xl font-semibold md:text-2xl">System Health &amp; Analytics</h1>

      <Suspense fallback={<div className="h-28 animate-pulse rounded-md bg-muted" />}>
        <HealthCards />
      </Suspense>

      <Suspense fallback={<div className="h-32 animate-pulse rounded-md bg-muted" />}>
        <MetricsCards />
      </Suspense>

      <div className="grid gap-4 md:gap-6 lg:grid-cols-2">
        <Suspense fallback={<div className="h-64 animate-pulse rounded-md bg-muted" />}>
          <QueryVolumeChart />
        </Suspense>
        <Suspense fallback={<div className="h-64 animate-pulse rounded-md bg-muted" />}>
          <TopSourcesTable />
        </Suspense>
      </div>

      <Suspense fallback={<div className="h-48 animate-pulse rounded-md bg-muted" />}>
        <ActivityFeed />
      </Suspense>
    </div>
  )
}
