import { Skeleton } from "@/components/ui/skeleton";
import type { UsageRow } from "@/lib/queries/ai";
import { formatCost, formatTokens, totals } from "@/lib/usage";

function Tile({
  label,
  value,
  sub,
  isLoading,
  isError,
}: {
  label: string;
  value: string;
  sub?: string;
  isLoading: boolean;
  isError: boolean;
}) {
  return (
    <div className="min-w-0 py-6 lg:border-l lg:pl-8 lg:first:border-l-0 lg:first:pl-0">
      <p className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        {label}
      </p>
      {isLoading ? (
        <Skeleton data-testid="usage-skeleton" className="mt-3 h-10 w-24" />
      ) : isError ? (
        <p className="mt-2 font-heading text-2xl font-semibold text-muted-foreground">
          Unavailable
        </p>
      ) : (
        <p className="mt-2 truncate font-heading text-4xl font-semibold tracking-tight">
          {value}
        </p>
      )}
      <p className="mt-1 min-h-5 text-sm text-muted-foreground">
        {isLoading || isError ? "" : sub}
      </p>
    </div>
  );
}

export function UsageSummary({
  rows,
  isLoading,
  isError,
}: {
  rows: UsageRow[];
  isLoading: boolean;
  isError: boolean;
}) {
  const t = totals(rows);
  const allUnpriced = t.calls > 0 && t.unpriced === t.calls;
  const state = { isLoading, isError };
  return (
    <div className="grid grid-cols-2 gap-x-8 border-y lg:grid-cols-4">
      <Tile label="Calls" value={t.calls.toLocaleString("en-US")} {...state} />
      <Tile label="Tokens in" value={formatTokens(t.tokensIn)} {...state} />
      <Tile label="Tokens out" value={formatTokens(t.tokensOut)} {...state} />
      <Tile
        label="Estimated cost"
        value={allUnpriced ? "Unpriced" : formatCost(t.cost)}
        sub={t.unpriced > 0 ? `${t.unpriced} ${t.unpriced === 1 ? "call" : "calls"} unpriced` : undefined}
        {...state}
      />
    </div>
  );
}
