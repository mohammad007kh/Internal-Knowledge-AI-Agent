import { Suspense } from 'react'
import { PermissionsManager } from './_components/PermissionsManager'

interface PermissionsPageProps {
  params: Promise<{ id: string }>
}

export default async function PermissionsPage({ params }: PermissionsPageProps) {
  const { id } = await params

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Manage Permissions</h1>
      <Suspense fallback={<div>Loading…</div>}>
        <PermissionsManager sourceId={id} />
      </Suspense>
    </div>
  )
}
