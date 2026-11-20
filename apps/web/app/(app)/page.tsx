"use client";

import Link from "next/link";
import { RecentClients } from "@/components/dashboard/recent-clients";
import { StatStrip } from "@/components/dashboard/stat-strip";
import { Button } from "@/components/ui/button";
import { useSession } from "@/lib/auth/session-store";

export default function HomePage() {
  const me = useSession((s) => s.me);
  if (!me) return null;

  return (
    <div className="flex flex-col gap-12">
      <header className="flex flex-col items-start gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            Agency overview
          </p>
          <h1 className="break-words font-heading text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
            {me.tenant_name}
          </h1>
        </div>
        {/* The create-client screen is built in the next stage. */}
        <Button size="lg" className="h-11 shrink-0 px-5" disabled title="Coming next">
          New client
        </Button>
      </header>

      <StatStrip role={me.role} />

      <section>
        <div className="mb-5 flex items-baseline justify-between">
          <h2 className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            Recent clients
          </h2>
          <Link href="/clients" className="text-sm text-muted-foreground hover:text-foreground">
            View all clients
          </Link>
        </div>
        <RecentClients />
      </section>
    </div>
  );
}
