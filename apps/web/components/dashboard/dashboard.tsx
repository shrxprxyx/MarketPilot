"use client";

import Link from "next/link";
import { NewClientDialog } from "@/components/clients/new-client-dialog";
import { GettingStarted } from "@/components/dashboard/getting-started";
import { RecentClients } from "@/components/dashboard/recent-clients";
import { StatStrip } from "@/components/dashboard/stat-strip";
import { useSession } from "@/lib/auth/session-store";

export function Dashboard() {
  const me = useSession((s) => s.me);
  if (!me) return null;
  const canWrite = me.role === "admin" || me.role === "manager"; // same rule as the clients API

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
        {canWrite && <NewClientDialog />}
      </header>

      <GettingStarted role={me.role} />

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
