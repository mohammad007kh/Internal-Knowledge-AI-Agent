export function ChatSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading conversation"
      className="flex flex-col gap-4 p-4"
    >
      {/* User message skeleton */}
      <div className="flex justify-end">
        <div className="h-10 w-48 animate-pulse rounded-lg bg-muted" />
      </div>
      {/* Assistant message skeleton */}
      <div className="flex flex-col gap-2">
        <div className="h-4 w-3/4 animate-pulse rounded bg-muted" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
        <div className="h-4 w-2/3 animate-pulse rounded bg-muted" />
      </div>
      {/* User message skeleton */}
      <div className="flex justify-end">
        <div className="h-10 w-32 animate-pulse rounded-lg bg-muted" />
      </div>
      {/* Assistant message skeleton */}
      <div className="flex flex-col gap-2">
        <div className="h-4 w-full animate-pulse rounded bg-muted" />
        <div className="h-4 w-4/5 animate-pulse rounded bg-muted" />
      </div>
    </div>
  );
}
