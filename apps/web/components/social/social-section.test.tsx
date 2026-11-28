import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SocialSection } from "@/components/social/social-section";
import { ApiError } from "@/lib/api/problem";
import { useSession, type Role } from "@/lib/auth/session-store";

const account = { id: "s1", client_id: "c1", platform: "facebook", handle: "acme", created_at: "" };
const metrics = {
  platform: "facebook",
  handle: "acme",
  posts: 3,
  followers: { start: 100, end: 150, growth: 50, growth_pct: 50 },
  engagement_rate: 12.5,
  trend: [],
  cadence: { posts: 3, per_week: 1.5 },
  best_days: [{ key: "Tue", posts: 1, avg_engagements: 9 }],
  best_hours_utc: [{ key: 18, posts: 1, avg_engagements: 9 }],
  best_formats: [{ key: "video", posts: 1, avg_engagements: 9 }],
  top_posts: [
    { ref: "p2", title: "Behind the scenes", format: "video", posted_at: "", engagements: 150, impressions: 2000 },
  ],
  bottom_posts: [],
};

let accounts: { data?: unknown[]; isLoading: boolean; isError: boolean } = {
  data: [account],
  isLoading: false,
  isError: false,
};
let metricsState: { data?: unknown; isLoading: boolean; isError: boolean } = {
  data: metrics,
  isLoading: false,
  isError: false,
};
const add = vi.fn();
const remove = vi.fn();
const importer = vi.fn();
vi.mock("@/lib/queries/social", async (orig) => ({
  ...(await orig<typeof import("@/lib/queries/social")>()),
  useSocialAccounts: () => accounts,
  useSocialMetrics: () => metricsState,
  useAddSocialAccount: () => ({ mutateAsync: (...a: unknown[]) => add(...a), isPending: false }),
  useDeleteSocialAccount: () => ({ mutate: (...a: unknown[]) => remove(...a), isPending: false }),
  useImportExport: () => ({ mutateAsync: (...a: unknown[]) => importer(...a), isPending: false }),
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
  accounts = { data: [account], isLoading: false, isError: false };
  metricsState = { data: metrics, isLoading: false, isError: false };
  add.mockReset();
  remove.mockReset();
  importer.mockReset();
  useSession.getState().clear();
});

describe("social metrics", () => {
  it("shows the metrics of each account", () => {
    as("manager");
    render(<SocialSection clientId="c1" />);
    expect(screen.getByText(/Facebook · @acme/)).toBeInTheDocument();
    expect(screen.getByText("12.5%")).toBeInTheDocument();
    expect(screen.getByText("+50 (50%)")).toBeInTheDocument();
    expect(screen.getByText("Behind the scenes")).toBeInTheDocument();
    expect(screen.getByText(/Best day: Tue/)).toBeInTheDocument();
  });

  it("asks for an import when there is no data yet", () => {
    as("manager");
    metricsState = {
      data: { ...metrics, posts: 0, followers: null },
      isLoading: false,
      isError: false,
    };
    render(<SocialSection clientId="c1" />);
    expect(screen.getByText("Import an export to see metrics.")).toBeInTheDocument();
  });

  it("says so when there are no accounts", () => {
    as("manager");
    accounts = { data: [], isLoading: false, isError: false };
    render(<SocialSection clientId="c1" />);
    expect(screen.getByText("No social accounts yet")).toBeInTheDocument();
  });
});

describe("roles", () => {
  it("lets a member read but not change anything", () => {
    as("member");
    render(<SocialSection clientId="c1" />);
    expect(screen.getByText(/Facebook · @acme/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add account" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove" })).not.toBeInTheDocument();
    expect(screen.queryByText("Import a performance export")).not.toBeInTheDocument();
  });
});

describe("accounts", () => {
  it("adds an account and clears the field", async () => {
    as("admin");
    add.mockResolvedValue({});
    render(<SocialSection clientId="c1" />);
    await userEvent.selectOptions(screen.getByLabelText("Platform"), "linkedin");
    await userEvent.type(screen.getByLabelText("Handle"), "@acme-co");
    await userEvent.click(screen.getByRole("button", { name: "Add account" }));
    expect(add).toHaveBeenCalledWith({ platform: "linkedin", handle: "@acme-co" });
    await waitFor(() => expect(screen.getByLabelText("Handle")).toHaveValue(""));
  });

  it("shows why an account could not be added", async () => {
    as("admin");
    add.mockRejectedValue(new ApiError(409, "Conflict", "This account is already added for the client."));
    render(<SocialSection clientId="c1" />);
    await userEvent.type(screen.getByLabelText("Handle"), "acme");
    await userEvent.click(screen.getByRole("button", { name: "Add account" }));
    expect(await screen.findByText(/already added/)).toBeInTheDocument();
  });

  it("removes an account", async () => {
    as("admin");
    render(<SocialSection clientId="c1" />);
    await userEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(remove).toHaveBeenCalledWith("s1");
  });
});

describe("import", () => {
  const csv = () => new File(["Publish time,Reach\n2026-11-02,1\n"], "export.csv", { type: "text/csv" });

  it("previews first and only saves after the user confirms", async () => {
    as("manager");
    importer
      .mockResolvedValueOnce({ committed: false, total: 2, valid: 2, errors: [], sample: [] })
      .mockResolvedValueOnce({ committed: true, total: 2, valid: 2, errors: [], sample: [] });
    render(<SocialSection clientId="c1" />);
    await userEvent.upload(screen.getByLabelText("Export file"), csv());
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(importer).toHaveBeenLastCalledWith(expect.objectContaining({ format: "csv", commit: false }));
    expect(await screen.findByText(/2 of 2 rows are valid/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Import 2 rows" }));
    expect(importer).toHaveBeenLastCalledWith(expect.objectContaining({ commit: true }));
    expect(await screen.findByText("Imported 2 rows.")).toBeInTheDocument();
  });

  it("lists bad rows and blocks the import", async () => {
    as("manager");
    importer.mockResolvedValue({
      committed: false,
      total: 2,
      valid: 1,
      errors: [{ row: 2, message: "Cannot read the date 'nope'." }],
      sample: [],
    });
    render(<SocialSection clientId="c1" />);
    await userEvent.upload(screen.getByLabelText("Export file"), csv());
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(/Row 2: Cannot read the date/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import 1 rows" })).toBeDisabled();
  });

  it("shows an unreadable file's reason", async () => {
    as("manager");
    importer.mockRejectedValue(new ApiError(422, "Unprocessable Entity", "The file is not valid JSON."));
    render(<SocialSection clientId="c1" />);
    await userEvent.upload(
      screen.getByLabelText("Export file"),
      new File(["{"], "export.json", { type: "application/json" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText("The file is not valid JSON.")).toBeInTheDocument();
    expect(importer).toHaveBeenLastCalledWith(expect.objectContaining({ format: "json" }));
  });
});
