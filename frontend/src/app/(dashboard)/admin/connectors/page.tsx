'use client'

import { ConnectorsTable } from '@/components/admin/ConnectorsTable'
import { Button } from '@/components/ui/button'
import { useRouter } from 'next/navigation'

export default function ConnectorsPage() {
  const router = useRouter()

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Connectors</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            Manage data source connectors and their credentials.
          </p>
        </div>
        <Button onClick={() => router.push('/admin/connectors/new')}>Add Connector</Button>
      </div>
      <ConnectorsTable />
    </div>
  )
}
