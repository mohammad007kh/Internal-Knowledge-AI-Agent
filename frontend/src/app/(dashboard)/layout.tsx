import { ThemeToggle } from "@/components/theme-toggle";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background">
      {/* Sidebar shell — full nav implemented in T-008 */}
      <aside className="hidden w-64 flex-col border-r border-border bg-card md:flex">
        <div className="flex h-14 items-center border-b border-border px-4">
          <span className="font-semibold text-card-foreground">Knowledge AI</span>
        </div>
        <nav className="flex-1 p-4">
          {/* Navigation links will be added in T-008 */}
        </nav>
        <div className="border-t border-border p-4">
          <ThemeToggle />
        </div>
      </aside>

      {/* Main content area */}
      <div className="flex flex-1 flex-col">
        <header className="flex h-14 items-center border-b border-border bg-card px-4 md:hidden">
          <span className="font-semibold text-card-foreground">Knowledge AI</span>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </header>
        <main className="flex-1">{children}</main>
      </div>
    </div>
  );
}
