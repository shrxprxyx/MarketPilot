"use client";

import Link from "next/link";
import { useState } from "react";
import { BreakdownTable } from "@/components/usage/breakdown-table";
import { DailyCostChart } from "@/components/usage/daily-cost-chart";
import { UsageSummary } from "@/components/usage/usage-summary";
import { useSession } from "@/lib/auth/session-store";
import { useAiUsageBy } from "@/lib/queries/ai";
import { useClients } from "@/lib/queries/clients";
import { totals } from "@/lib/usage";

const RANGES = [7, 30, 90] as const;

export function UsagePage() {
  const role = useSession((s) => s.me?.role);
  const [days, setDays] = useState<number>(30);
  const canView = role === "admin" || role === "manager";

  // Hooks run unconditionally; `enabled` keeps members from sending any usage request.
  const day = useAiUsageBy("day", days, canView);
  const client = useAiUsageBy("client", days, canView);
  const task = useAiUsageBy("task", days, canView);
  const model = useAiUsageBy("model", days, canView);
  const clients = useClients(100);

  if (!role) return null;

  const clientNames = new Map((clients.data?.items ?? []).map((c) => [c.id, c.name]));
  const clientLabel = (key: string | null) =>
    key === null ? "Unassigned" : (clientNames.get(key) ?? "Unknown client");

  const dayRows = day.data ?? [];
  const noCalls = !day.isLoading && !day.isError && totals(dayRows).calls === 0;

  return (
    <div className="flex max-w-5xl flex-col gap-12">
      <header className="flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            AI
          </p>
          <h1 className="font-heading text-4xl font-semibold leading-tight tracking-tight">
            Usage
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            See AI usage and estimated cost by day, client, task and model.
          </p>
        </div>
        {canView && (
          <div className="flex gap-2" role="group" aria-label="Date range">
            {RANGES.map((d) => (
              <button
                key={d}
                type="button"
                aria-pressed={days === d}
                onClick={() => setDays(d)}
                className="cursor-pointer rounded-md border px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground aria-pressed:border-foreground/40 aria-pressed:bg-white/[0.06] aria-pressed:text-foreground"
              >
                {d} days
              </button>
            ))}
          </div>
        )}
      </header>

      {!canView ? (
        <p className="border-y py-10 text-sm text-muted-foreground">
          Only admins and managers can view AI usage. Ask an admin if you need access.
        </p>
      ) : noCalls ? (
        <div className="border-y py-10">
          <p className="font-heading text-2xl font-semibold">No AI calls yet</p>
          <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
            Usage and cost appear here once your connected models start handling tasks. Make sure
            a model is connected and routed in{" "}
            <Link href="/settings/ai" className="text-foreground underline underline-offset-4">
              AI models
            </Link>
            .
          </p>
        </div>
      ) : (
        <>
          <UsageSummary rows={dayRows} isLoading={day.isLoading} isError={day.isError} />
          <DailyCostChart
            rows={dayRows}
            days={days}
            isLoading={day.isLoading}
            isError={day.isError}
          />
          <div className="grid gap-12 lg:grid-cols-2">
            <BreakdownTable
              title="By task"
              rows={task.data ?? []}
              isLoading={task.isLoading}
              isError={task.isError}
              label={(k) => k ?? "Unknown"}
            />
            <BreakdownTable
              title="By model"
              rows={model.data ?? []}
              isLoading={model.isLoading}
              isError={model.isError}
              label={(k) => k ?? "Unknown"}
            />
          </div>
          <BreakdownTable
            title="By client"
            rows={client.data ?? []}
            isLoading={client.isLoading}
            isError={client.isError}
            label={clientLabel}
          />
        </>
      )}
    </div>
  );
}
