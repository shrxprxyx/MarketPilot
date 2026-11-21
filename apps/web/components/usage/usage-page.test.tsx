import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UsagePage } from "@/components/usage/usage-page";
import { useSession, type Role } from "@/lib/auth/session-store";

const today = new Date().toISOString().slice(0, 10);
const r = (key: string | null, over = {}) => ({
  key,
  calls: 2,
  tokens_in: 100,
  tokens_out: 50,
  cost_usd: "1.5",
  unpriced_calls: 0,
  ...over,
});

let data: Record<string, unknown[]> = {};
let calls: [string, number, boolean][] = [];
vi.mock("@/lib/queries/ai", () => ({
  useAiUsageBy: (group: string, days: number, enabled: boolean) => {
    calls.push([group, days, enabled]);
    return { data: data[group] ?? [], isLoading: false, isError: false };
  },
}));
let budget: Record<string, unknown> | undefined;
const budgetFlags: boolean[] = [];
vi.mock("@/lib/queries/budget", () => ({
  useBudget: (enabled: boolean) => {
    budgetFlags.push(enabled);
    return { data: budget, isLoading: false, isError: false };
  },
}));
vi.mock("@/lib/queries/clients", () => ({
  useClients: () => ({
    data: { items: [{ id: "c1", name: "Acme" }], next_cursor: null },
    isLoading: false,
    isError: false,
  }),
}));

function as(role: Role) {
  useSession.getState().setSession("t", {
    user_id: "u",
    tenant_id: "t",
    role,
    email: "a@b.co",
    tenant_name: "Acme Agency",
  });
}

beforeEach(() => {
  calls = [];
  budget = undefined;
  budgetFlags.length = 0;
  data = {
    day: [r(today)],
    client: [r("c1"), r(null), r("gone-id")],
    task: [r("strategy")],
    model: [r("gpt-4o")],
  };
  useSession.getState().clear();
});

describe("UsagePage", () => {
  it("shows a managers-only message to members and never enables a usage request", () => {
    as("member");
    render(<UsagePage />);
    expect(screen.getByText(/only admins and managers/i)).toBeInTheDocument();
    expect(calls.length).toBeGreaterThan(0);
    expect(calls.every(([, , enabled]) => enabled === false)).toBe(true);
  });

  it.each(["admin", "manager"] as Role[])("loads all four groupings for 30 days for %s", (role) => {
    as(role);
    render(<UsagePage />);
    for (const g of ["day", "client", "task", "model"]) {
      expect(calls).toContainEqual([g, 30, true]);
    }
    expect(screen.getByRole("heading", { name: "Usage" })).toBeInTheDocument();
    expect(screen.getByText("strategy")).toBeInTheDocument();
    expect(screen.getByText("gpt-4o")).toBeInTheDocument();
  });

  it("shows the spend bar when a budget is set, and nothing when it is not", () => {
    as("admin");
    const { rerender } = render(<UsagePage />);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    budget = {
      monthly_budget_usd: "50.00",
      hard_stop: false,
      spent_usd: "42.50",
      percent_used: 85,
      unpriced_calls: 0,
      month: "2026-11",
    };
    rerender(<UsagePage />);
    expect(screen.getByRole("progressbar", { name: "Monthly AI budget used" })).toBeInTheDocument();
    expect(screen.getByText("85% of budget used")).toBeInTheDocument();
  });

  it("does not request the budget for members", () => {
    as("member");
    render(<UsagePage />);
    expect(budgetFlags.every((e) => e === false)).toBe(true);
  });

  it("re-queries every grouping when the range changes", async () => {
    as("admin");
    render(<UsagePage />);
    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
    calls = [];
    await userEvent.click(screen.getByRole("button", { name: "7 days" }));
    for (const g of ["day", "client", "task", "model"]) {
      expect(calls).toContainEqual([g, 7, true]);
    }
    expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
  });

  it("maps client ids to names, null to Unassigned and unknown ids to Unknown client", () => {
    as("admin");
    render(<UsagePage />);
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
    expect(screen.getByText("Unknown client")).toBeInTheDocument();
    expect(screen.queryByText("gone-id")).not.toBeInTheDocument();
  });

  it("shows an empty state linking to AI models when there are no calls", () => {
    as("admin");
    data = { day: [], client: [], task: [], model: [] };
    render(<UsagePage />);
    expect(screen.getByText("No AI calls yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /ai models/i })).toHaveAttribute("href", "/settings/ai");
  });
});
