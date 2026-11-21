"use client";

import Link from "next/link";
import { NewClientDialog } from "@/components/clients/new-client-dialog";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/lib/auth/session-store";
import { useClients } from "@/lib/queries/clients";

const LIMIT = 100;

export function ClientsList() {
  const role = useSession((s) => s.me?.role);
  const canWrite = role === "admin" || role === "manager";
  const { data, isLoading, isError } = useClients(LIMIT);
  const items = data?.items ?? [];

  return (
    <div className="flex max-w-5xl flex-col gap-10">
      <header className="flex flex-col items-start gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
            Workspace
          </p>
          <h1 className="font-heading text-4xl font-semibold leading-tight tracking-tight">
            Clients
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
            The businesses you run marketing for, with their knowledge documents.
          </p>
        </div>
        {canWrite && items.length > 0 && <NewClientDialog />}
      </header>

      {isLoading ? (
        <div className="flex flex-col gap-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} data-testid="client-skeleton" className="h-16 w-full" />
          ))}
        </div>
      ) : isError ? (
        <p className="text-sm text-muted-foreground">Couldn&apos;t load clients. Try again later.</p>
      ) : items.length === 0 ? (
        <div className="border-y py-10">
          <p className="font-heading text-2xl font-semibold">No clients yet</p>
          <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
            {canWrite
              ? "Add your first client to start building their knowledge base."
              : "Ask an admin or manager to add a client."}
          </p>
          {canWrite && (
            <div className="mt-5">
              <NewClientDialog />
            </div>
          )}
        </div>
      ) : (
        <>
          <ul className="divide-y border-y">
            {items.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/clients/${c.id}`}
                  className="flex items-center justify-between gap-4 py-5 transition-colors hover:bg-white/[0.03]"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{c.name}</span>
                    <span className="mt-1 block truncate text-sm text-muted-foreground">
                      {c.industry ?? "No industry set"}
                    </span>
                  </span>
                  <Badge variant="outline">{c.status}</Badge>
                </Link>
              </li>
            ))}
          </ul>
          {data?.next_cursor && (
            <p className="text-sm text-muted-foreground">Showing the first {LIMIT} clients</p>
          )}
        </>
      )}
    </div>
  );
}
