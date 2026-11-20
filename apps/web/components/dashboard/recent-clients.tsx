"use client";

import Link from "next/link";
import { Skeleton } from "@/components/ui/skeleton";
import { buttonVariants } from "@/components/ui/button";
import { useClients, type Client } from "@/lib/queries/clients";

function caption(c: Client): string {
  if (c.website_url) {
    try {
      return new URL(c.website_url).host;
    } catch {
      return c.website_url;
    }
  }
  return "No website";
}

const head =
  "pb-3 text-left font-mono text-[11px] font-normal uppercase tracking-[0.18em] text-muted-foreground";

export function RecentClients() {
  const { data, isLoading, isError } = useClients(100);

  if (isLoading) {
    return (
      <div data-testid="recent-skeleton" className="flex flex-col gap-4 py-4">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-12 w-full" />
        ))}
      </div>
    );
  }

  if (isError) {
    return <p className="py-10 text-sm text-muted-foreground">Couldn&apos;t load clients</p>;
  }

  const items = (data?.items ?? []).slice(0, 5);

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-start gap-3 border-y py-12">
        <p className="font-heading text-2xl font-semibold tracking-tight">No clients yet</p>
        <p className="max-w-md text-sm text-muted-foreground">
          Add your first client to start building their brand profile and knowledge base.
        </p>
        <Link href="/clients" className={buttonVariants({ variant: "secondary" })}>
          Create your first client
        </Link>
      </div>
    );
  }

  return (
    <table className="w-full table-fixed border-t">
      <thead>
        <tr>
          <th className={`${head} pt-4`}>Client</th>
          <th className={`${head} hidden pt-4 sm:table-cell`}>Industry</th>
          <th className={`${head} w-28 pt-4 text-right`}>Status</th>
        </tr>
      </thead>
      <tbody>
        {items.map((c) => (
          <tr key={c.id} className="border-t transition-colors hover:bg-white/[0.03]">
            <td className="min-w-0 py-4 pr-4">
              <Link href={`/clients/${c.id}`} className="block">
                <span className="block truncate font-medium">{c.name}</span>
                <span className="mt-0.5 block truncate font-mono text-xs text-muted-foreground">
                  {caption(c)}
                </span>
              </Link>
            </td>
            <td className="hidden truncate py-4 pr-4 text-sm text-muted-foreground sm:table-cell">
              {c.industry ?? "—"}
            </td>
            <td className="py-4 text-right">
              <span className="rounded border px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                {c.status}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
