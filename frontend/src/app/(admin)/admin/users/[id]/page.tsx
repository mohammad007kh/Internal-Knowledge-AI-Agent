import { redirect } from 'next/navigation'

interface UserDetailLegacyRouteProps {
  // Next.js 15 App Router: dynamic params resolve to a Promise.
  params: Promise<{ id: string }>
}

/**
 * Legacy route: superseded by the URL-driven View User Sheet (`?user=<id>`)
 * on `/admin/users`. Kept as a server-redirect so existing bookmarks / deep
 * links keep working.
 */
export default async function UserDetailLegacyRoute({
  params,
}: UserDetailLegacyRouteProps): Promise<never> {
  const { id } = await params
  redirect(`/admin/users?user=${id}`)
}
