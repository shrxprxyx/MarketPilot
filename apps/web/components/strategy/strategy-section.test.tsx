import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrategySection } from "@/components/strategy/strategy-section";
import { ApiError } from "@/lib/api/problem";
import { useSession, type Role } from "@/lib/auth/session-store";

const strategy = (over = {}) => ({
  id: "s1",
  client_id: "c1",
  month: "2026-12",
  version: 1,
  status: "draft",
  plan: {
    summary: "Grow subscriptions through email.",
    objectives: [{ title: "More subscribers", kpis: [{ name: "New subscribers", target: "200" }] }],
    channels: [{ name: "Email", rationale: "Highest retention." }],
    risks: [{ risk: "Supply delays", mitigation: "Buffer stock." }],
  },
  provider: "openai",
  model_used: "gpt-4o-mini",
  sources: [
    {
      chunk_id: "k1",
      document_id: "d1",
      document_title: "Coffee page",
      source_type: "brand_doc",
      excerpt: "Our espresso blends are roasted in small batches.",
    },
  ],
  tokens_in: 1200,
  tokens_out: 800,
  cost_usd: "0.0123",
  created_at: "2026-11-21T10:00:00Z",
  ...over,
});

let list: { data?: unknown[]; isLoading: boolean; isError: boolean } = {
  data: [strategy()],
  isLoading: false,
  isError: false,
};
let pending = false;
const generate = vi.fn();
vi.mock("@/lib/queries/strategies", () => ({
  useStrategies: () => list,
  useGenerateStrategy: () => ({ mutateAsync: (...a: unknown[]) => generate(...a), isPending: pending }),
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
const setList = (data: unknown[]) => {
  list = { data, isLoading: false, isError: false };
};
const thisMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

beforeEach(() => {
  setList([strategy()]);
  pending = false;
  generate.mockReset();
  useSession.getState().clear();
});

describe("states", () => {
  it("shows a skeleton, an empty state and an error state", () => {
    as("manager");
    list = { isLoading: true, isError: false };
    const { rerender } = render(<StrategySection clientId="c1" />);
    expect(screen.getByTestId("strategy-skeleton")).toBeInTheDocument();
    setList([]);
    rerender(<StrategySection clientId="c1" />);
    expect(screen.getByText("No strategies yet")).toBeInTheDocument();
    list = { isLoading: false, isError: true };
    rerender(<StrategySection clientId="c1" />);
    expect(screen.getByText(/couldn.t load strategies/i)).toBeInTheDocument();
  });
});

describe("plan view", () => {
  it("shows the summary, objectives with KPIs, channels and risks", () => {
    as("manager");
    render(<StrategySection clientId="c1" />);
    expect(screen.getByText("Grow subscriptions through email.")).toBeInTheDocument();
    expect(screen.getByText("More subscribers")).toBeInTheDocument();
    expect(screen.getByText(/New subscribers/)).toBeInTheDocument();
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getByText("Highest retention.")).toBeInTheDocument();
    expect(screen.getByText("Supply delays")).toBeInTheDocument();
    expect(screen.getByText("Buffer stock.")).toBeInTheDocument();
  });

  it("lists the sources used with their titles and excerpts", () => {
    as("manager");
    render(<StrategySection clientId="c1" />);
    const sources = screen.getByRole("region", { name: "Sources used" });
    expect(within(sources).getByText("Coffee page")).toBeInTheDocument();
    expect(within(sources).getByText(/espresso blends are roasted/)).toBeInTheDocument();
  });

  it("says so when no knowledge documents were used", () => {
    as("manager");
    setList([strategy({ sources: [] })]);
    render(<StrategySection clientId="c1" />);
    expect(screen.getByText("No knowledge documents were used")).toBeInTheDocument();
  });

  it("shows model, tokens and cost, and Cost unknown when unpriced", () => {
    as("manager");
    const { rerender } = render(<StrategySection clientId="c1" />);
    expect(screen.getByText("gpt-4o-mini")).toBeInTheDocument();
    expect(screen.getByText(/1,200 in/)).toBeInTheDocument();
    expect(screen.getByText(/800 out/)).toBeInTheDocument();
    expect(screen.getByText("$0.0123")).toBeInTheDocument();
    setList([strategy({ cost_usd: null })]);
    rerender(<StrategySection clientId="c1" />);
    expect(screen.getByText("Cost unknown")).toBeInTheDocument();
    expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
  });

  it("switches between versions", async () => {
    as("manager");
    setList([
      strategy({ id: "s2", version: 2, plan: { ...strategy().plan, summary: "Second plan" } }),
      strategy({ id: "s1", version: 1, plan: { ...strategy().plan, summary: "First plan" } }),
    ]);
    render(<StrategySection clientId="c1" />);
    expect(screen.getByText("Second plan")).toBeInTheDocument(); // newest first
    const v1 = screen.getByRole("button", { name: "2026-12 · v1" });
    expect(screen.getByRole("button", { name: "2026-12 · v2" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(v1);
    expect(screen.getByText("First plan")).toBeInTheDocument();
    expect(screen.queryByText("Second plan")).not.toBeInTheDocument();
  });
});

describe("generating", () => {
  it("defaults the month to the current month and sends it", async () => {
    as("manager");
    setList([]);
    generate.mockResolvedValue(strategy());
    render(<StrategySection clientId="c1" />);
    expect(screen.getByLabelText("Month")).toHaveValue(thisMonth());
    await userEvent.click(screen.getByRole("button", { name: "Generate strategy" }));
    expect(generate).toHaveBeenCalledWith({ month: thisMonth() });
  });

  it("offers Regenerate when the chosen month already has a version", () => {
    as("manager");
    setList([strategy({ month: thisMonth() })]);
    render(<StrategySection clientId="c1" />);
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeInTheDocument();
  });

  it("sends the month the user picked", async () => {
    as("manager");
    generate.mockResolvedValue(strategy());
    render(<StrategySection clientId="c1" />);
    const month = screen.getByLabelText("Month");
    await userEvent.clear(month);
    await userEvent.type(month, "2027-03");
    await userEvent.click(screen.getByRole("button", { name: "Generate strategy" }));
    expect(generate).toHaveBeenCalledWith({ month: "2027-03" });
  });

  it("shows the new strategy after generating", async () => {
    as("manager");
    generate.mockResolvedValue(
      strategy({ id: "s9", version: 3, plan: { ...strategy().plan, summary: "Fresh plan" } }),
    );
    render(<StrategySection clientId="c1" />);
    await userEvent.click(screen.getByRole("button", { name: "Generate strategy" }));
    expect(await screen.findByText("Fresh plan")).toBeInTheDocument();
  });

  it("disables the button and announces progress while generating", () => {
    as("manager");
    pending = true;
    render(<StrategySection clientId="c1" />);
    expect(screen.getByRole("button", { name: "Generating…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/generating/i);
  });

  it("links to AI models when no model is set up (409)", async () => {
    as("manager");
    generate.mockRejectedValue(
      new ApiError(409, "Conflict", "Set up a model for the strategy task in AI models."),
    );
    render(<StrategySection clientId="c1" />);
    await userEvent.click(screen.getByRole("button", { name: "Generate strategy" }));
    expect(await screen.findByText(/Set up a model for the strategy task/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open AI models" })).toHaveAttribute("href", "/settings/ai");
  });

  it("shows the provider's message when generation fails (502)", async () => {
    as("manager");
    generate.mockRejectedValue(new ApiError(502, "Bad Gateway", "The model call failed."));
    render(<StrategySection clientId="c1" />);
    await userEvent.click(screen.getByRole("button", { name: "Generate strategy" }));
    expect(await screen.findByText("The model call failed.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open AI models" })).not.toBeInTheDocument();
  });
});

describe("roles", () => {
  it("gives members a read-only view: plan and sources, no month or generate button", () => {
    as("member");
    render(<StrategySection clientId="c1" />);
    expect(screen.getByText("Grow subscriptions through email.")).toBeInTheDocument();
    expect(screen.queryByLabelText("Month")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate|regenerate/i })).not.toBeInTheDocument();
  });
});
