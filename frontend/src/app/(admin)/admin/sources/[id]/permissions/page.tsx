import { Suspense } from 'react'
import { PermissionsManager } from './_components/PermissionsManager'

interface PermissionsPageProps {
  params: Promise<{ id: string }>
}

export default async function PermissionsPage({ params }: PermissionsPageProps) {
  const { id } = await params

  return (
    <div className="space-y-4 p-4 md:space-y-6 md:p-6">
      <h1 className="text-xl font-bold md:text-2xl">Manage Permissions</h1>
      <Suspense fallback={<div>Loading…</div>}>
        <PermissionsManager sourceId={id} />
      </Suspense>
    </div>
  )
}
