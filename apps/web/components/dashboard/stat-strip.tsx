"use client";

import { Skeleton } from "@/components/ui/skeleton";
import type { Role } from "@/lib/auth/session-store";
import { useAiConnections, useAiUsage } from "@/lib/queries/ai";
import { useClients } from "@/lib/queries/clients";
import { useMembers } from "@/lib/queries/members";

type TileState = { isLoading?: boolean; isError?: boolean };

function Tile({
  label,
  state,
  value,
  sub,
}: {
  label: string;
  state: TileState;
  value: string;
  sub: string;
}) {
  return (
    <div data-tile className="min-w-0 py-6 lg:border-l lg:pl-8 lg:first:border-l-0 lg:first:pl-0">
      <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </p>
      {state.isLoading ? (
        <Skeleton data-testid="stat-skeleton" className="mt-3 h-10 w-24" />
      ) : state.isError ? (
        <p className="mt-2 font-heading text-2xl font-semibold text-muted-foreground">
          Unavailable
        </p>
      ) : (
        <p className="mt-2 truncate font-heading text-4xl font-semibold tracking-tight">
          {value}
        </p>
      )}
      <p className="mt-1 text-sm text-muted-foreground">
        {state.isError ? "Try again later" : state.isLoading ? " " : sub}
      </p>
    </div>
  );
}

const plural = (n: number, one: string, many: string) => (n === 1 ? `1 ${one}` : `${n} ${many}`);

const columns: Record<number, string> = {
  1: "lg:grid-cols-1",
  2: "lg:grid-cols-2",
  3: "lg:grid-cols-3",
  4: "lg:grid-cols-4",
};

export function StatStrip({ role }: { role: Role }) {
  const canManage = role === "admin" || role === "manager";
  const clients = useClients(100);
  // Restricted data is only requested for roles the API allows (no 403s from the dashboard).
  const connections = useAiConnections(canManage);
  const usage = useAiUsage(canManage);
  const members = useMembers(role === "admin");

  const clientList = clients.data;
  const clientCount = clientList
    ? `${clientList.items.length}${clientList.next_cursor ? "+" : ""}`
    : "";
  const activeClients = clientList?.items.filter((c) => c.status === "active").length ?? 0;

  const connList = connections.data ?? [];
  const activeConnections = connList.filter((c) => c.is_active).length;

  const rows = usage.data ?? [];
  const spend = rows.reduce((sum, r) => sum + Number(r.cost_usd), 0);
  const calls = rows.reduce((sum, r) => sum + r.calls, 0);
  const unpriced = rows.reduce((sum, r) => sum + r.unpriced_calls, 0);

  const activeMembers = (members.data ?? []).filter((m) => m.status === "active").length;

  const tiles = [
    <Tile
      key="clients"
      label="Clients"
      state={clients}
      value={clientCount}
      sub={`${activeClients} active`}
    />,
    ...(canManage
      ? [
          <Tile
            key="ai"
            label="AI models"
            state={connections}
            value={String(activeConnections)}
            sub={connList.length === 0 ? "Connect a model" : `of ${connList.length} connected`}
          />,
          <Tile
            key="spend"
            label="Spend · 30d"
            state={usage}
            value={`$${spend.toFixed(2)}`}
            sub={
              plural(calls, "call", "calls") + (unpriced > 0 ? ` · ${unpriced} unpriced` : "")
            }
          />,
        ]
      : []),
    ...(role === "admin"
      ? [
          <Tile
            key="team"
            label="Team"
            state={members}
            value={String(activeMembers)}
            sub="active members"
          />,
        ]
      : []),
  ];

  return (
    <div className={`grid grid-cols-2 gap-x-6 border-y ${columns[tiles.length]}`}>{tiles}</div>
  );
}
