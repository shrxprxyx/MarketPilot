import { render, screen, within } from "@testing-library/react";
import { BreakdownTable } from "@/components/usage/breakdown-table";
import type { UsageRow } from "@/lib/queries/ai";

const rows: UsageRow[] = [
  { key: "strategy", calls: 3, tokens_in: 12_500, tokens_out: 800, cost_usd: "0.0123", unpriced_calls: 0 },
  { key: null, calls: 1, tokens_in: 10, tokens_out: 5, cost_usd: "2", unpriced_calls: 0 },
];
const label = (k: string | null) => (k === null ? "Unassigned" : k.toUpperCase());

describe("BreakdownTable", () => {
  it("renders a titled row per entry using the label function and formatters", () => {
    render(<BreakdownTable title="By task" rows={rows} isLoading={false} isError={false} label={label} />);
    expect(screen.getByRole("heading", { name: "By task" })).toBeInTheDocument();
    const first = within(screen.getByText("STRATEGY").closest("tr")!);
    expect(first.getByText("3")).toBeInTheDocument();
    expect(first.getByText("12.5K")).toBeInTheDocument();
    expect(first.getByText("$0.0123")).toBeInTheDocument();
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
  });

  it("shows an empty message when there are no rows", () => {
    render(<BreakdownTable title="By task" rows={[]} isLoading={false} isError={false} label={label} />);
    expect(screen.getByText("No data in this range")).toBeInTheDocument();
  });

  it("shows a skeleton while loading and Unavailable on error", () => {
    const { rerender } = render(<BreakdownTable title="T" rows={[]} isLoading isError={false} label={label} />);
    expect(screen.getByTestId("usage-skeleton")).toBeInTheDocument();
    rerender(<BreakdownTable title="T" rows={[]} isLoading={false} isError label={label} />);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });
});
