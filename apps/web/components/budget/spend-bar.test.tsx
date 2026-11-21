import { render, screen } from "@testing-library/react";
import { SpendBar } from "@/components/budget/spend-bar";

const budget = (over = {}) => ({
  monthly_budget_usd: "50.00",
  hard_stop: false,
  spent_usd: "20.00",
  percent_used: 40,
  unpriced_calls: 0,
  month: "2026-11",
  ...over,
});

describe("SpendBar", () => {
  it("renders nothing without a budget", () => {
    const { container, rerender } = render(<SpendBar budget={undefined} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<SpendBar budget={budget({ monthly_budget_usd: null, percent_used: null })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows spend against the budget as a labelled progress bar", () => {
    render(<SpendBar budget={budget()} />);
    expect(screen.getByText("$20.00 of $50.00 used this month")).toBeInTheDocument();
    expect(screen.getByText("40% used")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Monthly AI budget used" });
    expect(bar).toHaveAttribute("aria-valuenow", "40");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
    expect(screen.queryByText(/budget reached/i)).not.toBeInTheDocument();
  });

  it("warns in words from 80%", () => {
    render(<SpendBar budget={budget({ spent_usd: "42.50", percent_used: 85 })} />);
    expect(screen.getByText("85% of budget used")).toBeInTheDocument();
  });

  it("says Budget reached at 100% and caps the bar at 100", () => {
    render(<SpendBar budget={budget({ spent_usd: "75.00", percent_used: 150 })} />);
    expect(screen.getByText("Budget reached")).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "100");
  });

  it("explains a hard stop once the budget is reached", () => {
    render(<SpendBar budget={budget({ percent_used: 100, hard_stop: true })} />);
    expect(screen.getByText(/AI generation is paused/i)).toBeInTheDocument();
  });

  it("notes unpriced calls that are not counted, singular and plural", () => {
    const { rerender } = render(<SpendBar budget={budget({ unpriced_calls: 1 })} />);
    expect(screen.getByText("1 unpriced call not counted")).toBeInTheDocument();
    rerender(<SpendBar budget={budget({ unpriced_calls: 3 })} />);
    expect(screen.getByText("3 unpriced calls not counted")).toBeInTheDocument();
  });
});
