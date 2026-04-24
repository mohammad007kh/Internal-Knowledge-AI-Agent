import { Button } from '@/components/ui/button'
import { PlusIcon } from 'lucide-react'
import Link from 'next/link'
import { Suspense } from 'react'
import { SourcesTable, SourcesTableSkeleton } from './_components/SourcesTable'

export default function SourcesPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Sources</h1>
        <Button asChild>
          <Link href="/admin/sources/new">
            <PlusIcon className="mr-2 h-4 w-4" />
            New Source
          </Link>
        </Button>
      </div>
      <Suspense fallback={<SourcesTableSkeleton />}>
        <SourcesTable />
      </Suspense>
    </div>
  )
}
