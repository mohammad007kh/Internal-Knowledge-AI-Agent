'use client'

import { ConnectorsTable } from '@/components/admin/ConnectorsTable'
import { Button } from '@/components/ui/button'
import { useRouter } from 'next/navigation'

export default function ConnectorsPage() {
  const router = useRouter()

  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl font-bold md:text-2xl">Connectors</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Manage data source connectors and their credentials.
          </p>
        </div>
        <Button
          className="w-full sm:w-auto"
          onClick={() => router.push('/admin/connectors/new')}
        >
          Add Connector
        </Button>
      </div>
      <ConnectorsTable />
    </div>
  )
}
