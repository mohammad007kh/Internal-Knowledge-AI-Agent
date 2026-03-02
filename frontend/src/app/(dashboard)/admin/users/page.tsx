import { UsersTable } from '@/components/admin/UsersTable'
import { Button } from '@/components/ui/button'
import { PlusIcon } from 'lucide-react'
import Link from 'next/link'
import { Suspense } from 'react'

export const metadata = { title: 'Users  Admin' }

export default function UsersPage() {
  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Users</h1>
        <Button asChild size="sm">
          <Link href="/admin/users/new">
            <PlusIcon className="mr-1.5 h-4 w-4" />
            Invite user
          </Link>
        </Button>
      </div>
      <Suspense fallback={<div className="h-64 animate-pulse rounded-md bg-muted" />}>
        <UsersTable />
      </Suspense>
    </div>
  )
}
