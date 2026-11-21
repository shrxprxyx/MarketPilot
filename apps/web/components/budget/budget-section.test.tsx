import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BudgetSection } from "@/components/budget/budget-section";
import { ApiError } from "@/lib/api/problem";
import { useSession, type Role } from "@/lib/auth/session-store";

const budget = (over = {}) => ({
  monthly_budget_usd: null as string | null,
  hard_stop: false,
  spent_usd: "20.00",
  percent_used: null as number | null,
  unpriced_calls: 0,
  month: "2026-11",
  ...over,
});

let state: { data?: ReturnType<typeof budget>; isLoading: boolean; isError: boolean } = {
  data: budget(),
  isLoading: false,
  isError: false,
};
const save = vi.fn();
const enabledFlags: boolean[] = [];
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/queries/budget", () => ({
  useBudget: (enabled: boolean) => {
    enabledFlags.push(enabled);
    return state;
  },
  useSaveBudget: () => ({ mutateAsync: (...a: unknown[]) => save(...a) }),
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
  state = { data: budget(), isLoading: false, isError: false };
  save.mockReset();
  enabledFlags.length = 0;
  useSession.getState().clear();
});

describe("BudgetSection", () => {
  it("lets an admin set an amount and a hard stop", async () => {
    as("admin");
    save.mockResolvedValue({});
    render(<BudgetSection />);
    await userEvent.type(screen.getByLabelText("Monthly budget (USD)"), "50");
    await userEvent.click(screen.getByLabelText(/stop ai calls when the budget is reached/i));
    await userEvent.click(screen.getByRole("button", { name: "Save budget" }));
    expect(save).toHaveBeenCalledWith({ monthly_budget_usd: 50, hard_stop: true });
  });

  it("shows the saved budget and spend", () => {
    as("admin");
    state = {
      data: budget({ monthly_budget_usd: "50.00", hard_stop: true, percent_used: 40 }),
      isLoading: false,
      isError: false,
    };
    render(<BudgetSection />);
    expect(screen.getByLabelText("Monthly budget (USD)")).toHaveValue("50");
    expect(screen.getByLabelText(/stop ai calls/i)).toBeChecked();
    expect(screen.getByText("$20.00 of $50.00 used this month")).toBeInTheDocument();
  });

  it("clears the budget when the amount is blank, and drops the hard stop", async () => {
    as("admin");
    state = {
      data: budget({ monthly_budget_usd: "50.00", hard_stop: true, percent_used: 40 }),
      isLoading: false,
      isError: false,
    };
    save.mockResolvedValue({});
    render(<BudgetSection />);
    await userEvent.clear(screen.getByLabelText("Monthly budget (USD)"));
    await userEvent.click(screen.getByRole("button", { name: "Save budget" }));
    expect(save).toHaveBeenCalledWith({ monthly_budget_usd: null, hard_stop: false });
  });

  it.each(["0", "-5", "abc", "1.234"])("rejects %s without sending anything", async (value) => {
    as("admin");
    render(<BudgetSection />);
    await userEvent.type(screen.getByLabelText("Monthly budget (USD)"), value);
    await userEvent.click(screen.getByRole("button", { name: "Save budget" }));
    expect(await screen.findByText(/amount above 0/i)).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("keeps Save disabled until something changes", () => {
    as("admin");
    render(<BudgetSection />);
    expect(screen.getByRole("button", { name: "Save budget" })).toBeDisabled();
  });

  it("shows the API detail when saving fails", async () => {
    as("admin");
    save.mockRejectedValue(new ApiError(403, "Forbidden", "Not allowed."));
    render(<BudgetSection />);
    await userEvent.type(screen.getByLabelText("Monthly budget (USD)"), "10");
    await userEvent.click(screen.getByRole("button", { name: "Save budget" }));
    expect(await screen.findByText("Not allowed.")).toBeInTheDocument();
  });

  it("gives managers a read-only view: spend bar but no form", () => {
    as("manager");
    state = {
      data: budget({ monthly_budget_usd: "50.00", percent_used: 40 }),
      isLoading: false,
      isError: false,
    };
    render(<BudgetSection />);
    expect(screen.getByText("$20.00 of $50.00 used this month")).toBeInTheDocument();
    expect(screen.queryByLabelText("Monthly budget (USD)")).not.toBeInTheDocument();
    expect(screen.getByText(/only admins can change the budget/i)).toBeInTheDocument();
  });

  it("renders nothing for members and never requests the budget", () => {
    as("member");
    const { container } = render(<BudgetSection />);
    expect(container).toBeEmptyDOMElement();
    expect(enabledFlags.every((e) => e === false)).toBe(true);
  });

  it("shows a skeleton while loading", () => {
    as("admin");
    state = { isLoading: true, isError: false };
    render(<BudgetSection />);
    expect(screen.getByTestId("budget-skeleton")).toBeInTheDocument();
  });
});
