import { Sidebar } from "@/components/shell/sidebar";
import { Topbar } from "@/components/shell/topbar";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-svh flex-1">
      <aside className="sticky top-0 hidden h-svh w-72 shrink-0 border-r lg:block">
        <Sidebar />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar />
        <main className="flex-1 p-6 lg:p-10">{children}</main>
      </div>
    </div>
  );
}
