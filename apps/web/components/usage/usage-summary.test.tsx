import { render, screen } from "@testing-library/react";
import { UsageSummary } from "@/components/usage/usage-summary";
import type { UsageRow } from "@/lib/queries/ai";

const row = (over: Partial<UsageRow> = {}): UsageRow => ({
  key: "2026-11-20",
  calls: 1,
  tokens_in: 0,
  tokens_out: 0,
  cost_usd: "0",
  unpriced_calls: 0,
  ...over,
});

const rows = [
  row({ calls: 5, tokens_in: 1000, tokens_out: 234, cost_usd: "1.0" }),
  row({ calls: 7, tokens_in: 234, tokens_out: 333, cost_usd: "0.25" }),
];

describe("UsageSummary", () => {
  it("shows calls, tokens in and out, and estimated cost", () => {
    render(<UsageSummary rows={rows} isLoading={false} isError={false} />);
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("1,234")).toBeInTheDocument();
    expect(screen.getByText("567")).toBeInTheDocument();
    expect(screen.getByText("$1.25")).toBeInTheDocument();
  });

  it("notes how many calls are unpriced", () => {
    render(
      <UsageSummary
        rows={[row({ calls: 5, cost_usd: "1", unpriced_calls: 2 })]}
        isLoading={false}
        isError={false}
      />,
    );
    expect(screen.getByText(/2 calls unpriced/i)).toBeInTheDocument();
  });

  it("says unpriced instead of a confident $0.00 when every call is unpriced", () => {
    render(
      <UsageSummary
        rows={[row({ calls: 3, cost_usd: "0", unpriced_calls: 3 })]}
        isLoading={false}
        isError={false}
      />,
    );
    expect(screen.getByText("Unpriced")).toBeInTheDocument();
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
  });

  it("shows skeletons while loading and Unavailable on error", () => {
    const { rerender } = render(<UsageSummary rows={[]} isLoading isError={false} />);
    expect(screen.getAllByTestId("usage-skeleton").length).toBeGreaterThan(0);
    rerender(<UsageSummary rows={[]} isLoading={false} isError />);
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
  });
});
