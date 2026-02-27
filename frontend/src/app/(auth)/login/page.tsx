export default function LoginPage() {
  return (
    <div className="rounded-lg border border-border bg-card p-8 shadow-sm">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold tracking-tight text-card-foreground">
          Knowledge AI Agent
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Sign in to access your knowledge base
        </p>
      </div>
      {/* Login form will be implemented in T-006 */}
      <p className="text-center text-sm text-muted-foreground">
        Authentication form coming soon.
      </p>
    </div>
  );
}
