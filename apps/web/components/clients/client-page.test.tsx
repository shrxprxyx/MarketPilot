import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ClientPage } from "@/components/clients/client-page";
import { ApiError } from "@/lib/api/problem";

const client = (over = {}) => ({
  id: "c1",
  name: "Acme Pets",
  website_url: null,
  industry: null,
  goals: null,
  status: "active",
  ...over,
});

let query: { data?: unknown; isLoading: boolean; error: unknown } = {
  data: client(),
  isLoading: false,
  error: null,
};
vi.mock("@/lib/queries/clients", () => ({ useClient: () => query }));
vi.mock("@/components/clients/client-overview", () => ({
  ClientOverview: ({ client: c }: { client: { name: string } }) => <div>overview-panel {c.name}</div>,
}));
vi.mock("@/components/clients/brand-profile-form", () => ({
  BrandProfileForm: ({ clientId }: { clientId: string }) => (
    <div>
      brand-panel {clientId}
      <input aria-label="draft" />
    </div>
  ),
}));
vi.mock("@/components/knowledge/knowledge-section", () => ({
  KnowledgeSection: ({ clientId }: { clientId: string }) => <div>knowledge-panel {clientId}</div>,
}));

vi.mock("@/components/audits/audits-section", () => ({
  AuditsSection: ({ clientId }: { clientId: string }) => <div>audits-panel {clientId}</div>,
}));
vi.mock("@/components/strategy/strategy-section", () => ({
  StrategySection: ({ clientId }: { clientId: string }) => <div>strategy-panel {clientId}</div>,
}));

beforeEach(() => {
  query = { data: client(), isLoading: false, error: null };
});

describe("ClientPage", () => {
  it("shows the client name as the heading", () => {
    render(<ClientPage id="c1" />);
    expect(screen.getByRole("heading", { name: "Acme Pets" })).toBeInTheDocument();
    expect(screen.queryByText("Archived")).not.toBeInTheDocument();
  });

  it("marks an archived client in the header", () => {
    query = { data: client({ status: "archived" }), isLoading: false, error: null };
    render(<ClientPage id="c1" />);
    expect(screen.getByText("Archived")).toBeInTheDocument();
  });

  it("has Overview, Brand profile, Knowledge, Strategy and Audits tabs, with Overview selected first", () => {
    render(<ClientPage id="c1" />);
    expect(screen.getAllByRole("tab").map((t) => t.textContent)).toEqual([
      "Overview",
      "Brand profile",
      "Knowledge",
      "Strategy",
      "Audits",
      "Social",
    ]);
    expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("overview-panel Acme Pets")).toBeInTheDocument();
    expect(screen.queryByText("brand-panel c1")).not.toBeVisible();
  });

  it("keeps unsaved brand profile edits when switching tabs and back", async () => {
    render(<ClientPage id="c1" />);
    await userEvent.click(screen.getByRole("tab", { name: "Brand profile" }));
    await userEvent.type(screen.getByLabelText("draft"), "bold and warm");
    await userEvent.click(screen.getByRole("tab", { name: "Knowledge" }));
    await userEvent.click(screen.getByRole("tab", { name: "Brand profile" }));
    expect(screen.getByLabelText("draft")).toHaveValue("bold and warm");
  });

  it("shows only the selected tab's panel, passing it the client id", async () => {
    render(<ClientPage id="c1" />);
    await userEvent.click(screen.getByRole("tab", { name: "Brand profile" }));
    expect(screen.getByText("brand-panel c1")).toBeInTheDocument();
    expect(screen.queryByText(/overview-panel/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Knowledge" }));
    expect(screen.getByText("knowledge-panel c1")).toBeInTheDocument();
    expect(screen.queryByText("brand-panel c1")).not.toBeVisible();
    await userEvent.click(screen.getByRole("tab", { name: "Strategy" }));
    expect(screen.getByText("strategy-panel c1")).toBeInTheDocument();
    expect(screen.queryByText("knowledge-panel c1")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Audits" }));
    expect(screen.getByText("audits-panel c1")).toBeInTheDocument();
  });

  it("shows a skeleton while loading", () => {
    query = { isLoading: true, error: null };
    render(<ClientPage id="c1" />);
    expect(screen.getByTestId("client-skeleton")).toBeInTheDocument();
  });

  it("shows Client not found with a link back for a 404", () => {
    query = { isLoading: false, error: new ApiError(404, "Not Found", "Client not found.") };
    render(<ClientPage id="nope" />);
    expect(screen.getByText("Client not found")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to clients/i })).toHaveAttribute("href", "/clients");
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });

  it("shows the detail for any other error", () => {
    query = { isLoading: false, error: new ApiError(500, "Error", "Server exploded.") };
    render(<ClientPage id="c1" />);
    expect(screen.getByText("Server exploded.")).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });
});
