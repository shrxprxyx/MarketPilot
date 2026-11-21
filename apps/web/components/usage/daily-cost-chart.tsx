"use client";

import { useState } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import type { UsageRow } from "@/lib/queries/ai";
import { fillDays, formatCost, totals } from "@/lib/usage";

// Series 1 from the validated dataviz palette (dark step); one series, so no legend.
const BAR = "#3987e5";
const W = 720;
const H = 220;
const PAD = { top: 12, right: 8, bottom: 26, left: 52 };
const MAX_BAR = 24; // marks stay thin: never fill the slot
const GAP = 2;

/** Bar with a 4px rounded data end and a square baseline. */
function barPath(x: number, base: number, w: number, h: number) {
  if (h <= 0) return `M${x},${base}h${w}`;
  const r = Math.min(4, h, w / 2);
  return `M${x},${base}v${-(h - r)}a${r},${r} 0 0 1 ${r},${-r}h${w - 2 * r}a${r},${r} 0 0 1 ${r},${r}v${h - r}z`;
}

export function DailyCostChart({
  rows,
  days,
  isLoading,
  isError,
}: {
  rows: UsageRow[];
  days: number;
  isLoading: boolean;
  isError: boolean;
}) {
  const [active, setActive] = useState<number | null>(null);

  if (isLoading) return <Skeleton data-testid="usage-skeleton" className="h-56 w-full" />;
  if (isError) return <p className="text-sm text-muted-foreground">Unavailable</p>;

  const t = totals(rows);
  if (t.calls === 0) {
    return (
      <p className="border-y py-10 text-sm text-muted-foreground">No calls in this range</p>
    );
  }

  // If nothing has a price, cost would be a flat zero line: plot calls instead.
  const byCalls = t.cost === 0;
  const series = fillDays(rows, days);
  const value = (r: UsageRow) => (byCalls ? r.calls : Number(r.cost_usd));
  const fmt = (n: number) => (byCalls ? `${n} ${n === 1 ? "call" : "calls"}` : formatCost(n));
  const values = series.map(value);
  const max = Math.max(...values);
  const peakIndex = values.indexOf(max);
  const total = byCalls ? t.calls : t.cost;
  const title = byCalls ? "Daily calls" : "Daily cost";

  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const base = PAD.top + plotH;
  const slot = plotW / days;
  const barW = Math.max(1, Math.min(MAX_BAR, slot - GAP));
  const shown = active ?? peakIndex;

  const label = `${title} over ${days} days: total ${fmt(total)}, peak ${series[peakIndex].key} (${fmt(max)})`;
  const ticks = [0, max / 2, max];

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          {title}
        </h3>
        <p aria-live="polite" className="text-sm tabular-nums text-muted-foreground">
          {series[shown].key} · <span className="text-foreground">{fmt(values[shown])}</span>
        </p>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={label}
        className="h-auto w-full"
        onMouseLeave={() => setActive(null)}
      >
        {ticks.map((tick) => {
          const y = base - (max === 0 ? 0 : (tick / max) * plotH);
          return (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={W - PAD.right}
                y1={y}
                y2={y}
                stroke="currentColor"
                strokeOpacity={tick === 0 ? 0.25 : 0.1}
              />
              <text
                x={PAD.left - 8}
                y={y + 4}
                textAnchor="end"
                className="fill-muted-foreground text-[10px]"
              >
                {byCalls ? Math.round(tick) : formatCost(tick)}
              </text>
            </g>
          );
        })}
        {series.map((r, i) => {
          const h = max === 0 ? 0 : (values[i] / max) * plotH;
          const x = PAD.left + i * slot + (slot - barW) / 2;
          return (
            <g
              key={r.key}
              data-bar
              data-value={String(values[i])}
              tabIndex={0}
              onMouseEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              className="outline-none"
            >
              {/* Hit target spans the full column, larger than the mark. */}
              <rect
                x={PAD.left + i * slot}
                y={PAD.top}
                width={slot}
                height={plotH}
                fill="transparent"
              />
              <path
                d={barPath(x, base, barW, h)}
                fill={BAR}
                fillOpacity={active === null || active === i ? 1 : 0.45}
                stroke={h === 0 ? BAR : "none"}
              />
            </g>
          );
        })}
        {[0, Math.floor((days - 1) / 2), days - 1].map((i, n) => (
          <text
            key={n}
            x={PAD.left + i * slot + slot / 2}
            y={H - 6}
            textAnchor={n === 0 ? "start" : n === 2 ? "end" : "middle"}
            className="fill-muted-foreground text-[10px]"
          >
            {series[i].key!.slice(5)}
          </text>
        ))}
      </svg>
      <table className="sr-only">
        <caption>Usage per day</caption>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">{byCalls ? "Calls" : "Cost"}</th>
          </tr>
        </thead>
        <tbody>
          {series.map((r, i) => (
            <tr key={r.key}>
              <th scope="row">{r.key}</th>
              <td>{fmt(values[i])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
