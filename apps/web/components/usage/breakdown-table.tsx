import { Skeleton } from "@/components/ui/skeleton";
import type { UsageRow } from "@/lib/queries/ai";
import { formatCost, formatTokens } from "@/lib/usage";

export function BreakdownTable({
  title,
  rows,
  isLoading,
  isError,
  label,
}: {
  title: string;
  rows: UsageRow[];
  isLoading: boolean;
  isError: boolean;
  label: (key: string | null) => string;
}) {
  return (
    <section>
      <h2 className="mb-5 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        {title}
      </h2>
      {isLoading ? (
        <Skeleton data-testid="usage-skeleton" className="h-24 w-full" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">Unavailable</p>
      ) : rows.length === 0 ? (
        <p className="border-y py-6 text-sm text-muted-foreground">No data in this range</p>
      ) : (
        <div className="overflow-x-auto border-y">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
                <th scope="col" className="py-3 pr-4 font-normal">Name</th>
                <th scope="col" className="px-4 py-3 text-right font-normal">Calls</th>
                <th scope="col" className="px-4 py-3 text-right font-normal">Tokens in</th>
                <th scope="col" className="px-4 py-3 text-right font-normal">Tokens out</th>
                <th scope="col" className="py-3 pl-4 text-right font-normal">Cost</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map((r) => (
                <tr key={r.key ?? "none"}>
                  <th scope="row" className="max-w-56 truncate py-3 pr-4 text-left font-normal">
                    {label(r.key)}
                  </th>
                  <td className="px-4 py-3 text-right tabular-nums">{r.calls}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{formatTokens(r.tokens_in)}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{formatTokens(r.tokens_out)}</td>
                  <td className="py-3 pl-4 text-right tabular-nums">
                    {formatCost(r.cost_usd)}
                    {r.unpriced_calls > 0 && (
                      <span className="ml-1 text-muted-foreground">*</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.some((r) => r.unpriced_calls > 0) && (
            <p className="border-t py-2 text-xs text-muted-foreground">
              * Includes calls with no known price, counted as $0.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
