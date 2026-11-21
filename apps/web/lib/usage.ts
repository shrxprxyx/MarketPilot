import type { UsageRow } from "@/lib/queries/ai";

export function totals(rows: UsageRow[]) {
  return rows.reduce(
    (t, r) => ({
      calls: t.calls + r.calls,
      tokensIn: t.tokensIn + r.tokens_in,
      tokensOut: t.tokensOut + r.tokens_out,
      cost: t.cost + Number(r.cost_usd),
      unpriced: t.unpriced + r.unpriced_calls,
    }),
    { calls: 0, tokensIn: 0, tokensOut: 0, cost: 0, unpriced: 0 },
  );
}

/** Four decimals under $1 so tiny costs never read as $0.00; two from $1 up. */
export function formatCost(value: string | number): string {
  const n = Number(value);
  if (n === 0) return "$0.00";
  return n < 1 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`;
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(2)}M`;
  if (n >= 10_000) return `${+(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString("en-US");
}

const dayKey = (d: Date) => d.toISOString().slice(0, 10);

/** Exactly `days` rows ending today (UTC), oldest first; days with no calls are zeroed. */
export function fillDays(rows: UsageRow[], days: number, today: Date = new Date()): UsageRow[] {
  const byDay = new Map(rows.map((r) => [r.key, r]));
  return Array.from({ length: days }, (_, i) => {
    const d = new Date(today);
    d.setUTCDate(d.getUTCDate() - (days - 1 - i));
    const key = dayKey(d);
    return (
      byDay.get(key) ?? {
        key,
        calls: 0,
        tokens_in: 0,
        tokens_out: 0,
        cost_usd: "0",
        unpriced_calls: 0,
      }
    );
  });
}
