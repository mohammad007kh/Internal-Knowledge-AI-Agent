import { redirect } from 'next/navigation'

/**
 * Legacy route: superseded by the URL-driven Invite Dialog (`?invite=1`)
 * on `/admin/users`. Kept as a server-redirect so existing bookmarks /
 * deep links from emails keep working.
 */
export default function InviteUserLegacyRoute(): never {
  redirect('/admin/users?invite=1')
}
