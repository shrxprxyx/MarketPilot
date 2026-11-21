import { formatCost } from "@/lib/usage";
import type { Budget } from "@/lib/queries/budget";

/** Spend against the monthly budget. Status is always spelled out, never colour alone. */
export function SpendBar({ budget }: { budget: Budget | undefined }) {
  if (!budget || budget.monthly_budget_usd === null) return null;

  const percent = budget.percent_used ?? 0;
  const reached = percent >= 100;
  const warning = percent >= 80;
  const label = reached
    ? "Budget reached"
    : warning
      ? `${Math.round(percent)}% of budget used`
      : `${Math.round(percent)}% used`;
  const fill = reached ? "bg-red-500" : warning ? "bg-amber-400" : "bg-foreground/70";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span>
          {formatCost(budget.spent_usd)} of {formatCost(budget.monthly_budget_usd)} used this month
        </span>
        <span className={reached ? "font-medium text-red-400" : warning ? "text-amber-300" : "text-muted-foreground"}>
          {label}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label="Monthly AI budget used"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.min(100, Math.round(percent))}
        className="h-2 w-full overflow-hidden rounded-full bg-white/10"
      >
        <div className={`h-full rounded-full ${fill}`} style={{ width: `${Math.min(100, percent)}%` }} />
      </div>
      {reached && budget.hard_stop && (
        <p className="text-sm text-muted-foreground">
          AI generation is paused until the budget is raised or the month rolls over.
        </p>
      )}
      {budget.unpriced_calls > 0 && (
        <p className="text-xs text-muted-foreground">
          {budget.unpriced_calls} unpriced {budget.unpriced_calls === 1 ? "call" : "calls"} not counted
        </p>
      )}
    </div>
  );
}
