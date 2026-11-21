import { render, screen } from "@testing-library/react";
import { DailyCostChart } from "@/components/usage/daily-cost-chart";
import type { UsageRow } from "@/lib/queries/ai";

const today = new Date().toISOString().slice(0, 10);
const row = (over: Partial<UsageRow> = {}): UsageRow => ({
  key: today,
  calls: 2,
  tokens_in: 10,
  tokens_out: 5,
  cost_usd: "3",
  unpriced_calls: 0,
  ...over,
});
const bars = (c: HTMLElement) => [...c.querySelectorAll("[data-bar]")];

describe("DailyCostChart", () => {
  it("draws a bar for every calendar day the API window touches (days + 1), including zero days", () => {
    const { container } = render(
      <DailyCostChart rows={[row()]} days={7} isLoading={false} isError={false} />,
    );
    const all = bars(container);
    expect(all).toHaveLength(8);
    expect(all[0].getAttribute("data-value")).toBe("0");
    expect(all[7].getAttribute("data-value")).toBe("3");
  });

  it("keeps the boundary day so the bars add up to the stated total", () => {
    const d = new Date();
    d.setUTCDate(d.getUTCDate() - 7);
    const boundary = d.toISOString().slice(0, 10);
    const { container } = render(
      <DailyCostChart
        rows={[row({ key: boundary, cost_usd: "1" }), row()]}
        days={7}
        isLoading={false}
        isError={false}
      />,
    );
    const sum = bars(container).reduce((n, b) => n + Number(b.getAttribute("data-value")), 0);
    expect(sum).toBe(4);
    expect(screen.getByRole("img").getAttribute("aria-label")).toContain("$4.00");
  });

  it("describes total and peak in an accessible label", () => {
    render(<DailyCostChart rows={[row()]} days={7} isLoading={false} isError={false} />);
    const label = screen.getByRole("img").getAttribute("aria-label") ?? "";
    expect(label).toMatch(/daily cost/i);
    expect(label).toContain("$3.00");
    expect(label).toContain(today);
  });

  it("plots calls instead of cost when every call is unpriced", () => {
    render(
      <DailyCostChart
        rows={[row({ cost_usd: "0", calls: 4, unpriced_calls: 4 })]}
        days={7}
        isLoading={false}
        isError={false}
      />,
    );
    expect(screen.getByText(/daily calls/i)).toBeInTheDocument();
    expect(screen.getByRole("img").getAttribute("aria-label")).toMatch(/calls/i);
  });

  it("shows an empty message and no chart when there are no calls", () => {
    render(<DailyCostChart rows={[]} days={7} isLoading={false} isError={false} />);
    expect(screen.getByText(/no calls in this range/i)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows a skeleton while loading and Unavailable on error", () => {
    const { rerender } = render(<DailyCostChart rows={[]} days={7} isLoading isError={false} />);
    expect(screen.getByTestId("usage-skeleton")).toBeInTheDocument();
    rerender(<DailyCostChart rows={[]} days={7} isLoading={false} isError />);
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });
});
