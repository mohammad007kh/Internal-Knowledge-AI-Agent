import type { Metadata } from 'next'
import { AnalyticsDashboard } from './_components/AnalyticsDashboard'

export const metadata: Metadata = {
  title: 'Analytics — Admin',
}

export default function AnalyticsPage() {
  return <AnalyticsDashboard />
}
