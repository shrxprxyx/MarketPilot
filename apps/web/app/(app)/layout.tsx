import { Suspense } from "react";
import { AppShell } from "@/components/shell/app-shell";
import { SessionGate } from "@/components/session-gate";
import { Skeleton } from "@/components/ui/skeleton";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    // Dynamic routes (e.g. /clients/[id]) make the pathname request-time data, and
    // the shell reads it, so a Suspense boundary is required above it.
    <Suspense fallback={<Skeleton className="m-8 h-8 w-48" />}>
      <SessionGate>
        <AppShell>{children}</AppShell>
      </SessionGate>
    </Suspense>
  );
}
