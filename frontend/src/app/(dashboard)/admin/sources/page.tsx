import { Suspense } from 'react'
import { CreateSourceDialog } from './_components/CreateSourceDialog'
import { SourcesTable } from './_components/SourcesTable'

export default function SourcesPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Sources</h1>
        <CreateSourceDialog />
      </div>
      <Suspense fallback={<div>Loading…</div>}>
        <SourcesTable />
      </Suspense>
    </div>
  )
}
