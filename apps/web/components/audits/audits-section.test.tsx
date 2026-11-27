import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuditsSection } from "@/components/audits/audits-section";
import { ApiError } from "@/lib/api/problem";
import { useSession, type Role } from "@/lib/auth/session-store";

const audit = (over = {}) => ({
  id: "a1",
  client_id: "c1",
  type: "website",
  url: "https://acme.test",
  status: "succeeded",
  score: 72,
  summary: {
    categories: { technical: 90, on_page: 60, links: 80, mobile: 100 },
    severity_counts: { high: 1, low: 2 },
    pages_crawled: 14,
    truncated: false,
  },
  error: null,
  created_at: "2026-11-27T10:00:00Z",
  finished_at: "2026-11-27T10:02:00Z",
  job_id: null,
  ...over,
});
const finding = (over = {}) => ({
  id: "f1",
  code: "title_missing",
  category: "on_page",
  severity: "high",
  title: "Page has no title",
  detail: "The page has no title tag.",
  url: "https://acme.test/about",
  recommendation: "Add a title of 30 to 60 characters.",
  ...over,
});

let list: { data?: { items: unknown[] }; isLoading: boolean; isError: boolean; progress: object } = {
  isLoading: false,
  isError: false,
  progress: {},
};
let findings: { data?: { items: unknown[] }; isLoading: boolean; isError: boolean } = {
  data: { items: [finding()] },
  isLoading: false,
  isError: false,
};
const severities: (string | null)[] = [];
const start = vi.fn();
vi.mock("@/lib/queries/audits", async (orig) => ({
  ...(await orig<typeof import("@/lib/queries/audits")>()),
  useAudits: () => list,
  useStartAudit: () => ({ mutateAsync: (...a: unknown[]) => start(...a), isPending: false }),
  useFindings: (_id: string, severity: string | null) => {
    severities.push(severity);
    return findings;
  },
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
const setAudits = (items: unknown[], progress = {}) => {
  list = { data: { items }, isLoading: false, isError: false, progress };
};

beforeEach(() => {
  setAudits([audit()]);
  findings = { data: { items: [finding()] }, isLoading: false, isError: false };
  severities.length = 0;
  start.mockReset();
  useSession.getState().clear();
});

describe("audit result", () => {
  it("shows the score, the category scores and what was crawled", () => {
    as("manager");
    render(<AuditsSection clientId="c1" />);
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.getByText("On-page")).toBeInTheDocument();
    expect(screen.getByText("60")).toBeInTheDocument();
    expect(screen.getByText(/14 pages crawled/)).toBeInTheDocument();
  });

  it("lists findings with their fix", () => {
    as("manager");
    render(<AuditsSection clientId="c1" />);
    expect(screen.getByText("Page has no title")).toBeInTheDocument();
    expect(screen.getByText(/Add a title of 30 to 60 characters/)).toBeInTheDocument();
  });

  it("filters findings by severity, with a count on each filter", async () => {
    as("manager");
    render(<AuditsSection clientId="c1" />);
    expect(screen.getByRole("button", { name: "All (3)" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Critical (0)" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Low (2)" }));
    expect(severities.at(-1)).toBe("low");
    expect(screen.getByRole("button", { name: "Low (2)" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "All (3)" }));
    expect(severities.at(-1)).toBeNull();
  });

  it("says so when a filter has no findings", () => {
    as("manager");
    findings = { data: { items: [] }, isLoading: false, isError: false };
    render(<AuditsSection clientId="c1" />);
    expect(screen.getByText("No issues found")).toBeInTheDocument();
  });
});

describe("audit in progress", () => {
  it("shows live progress and disables starting another audit", () => {
    as("manager");
    setAudits([audit({ status: "running", score: null, summary: null, job_id: "j1" })], {
      a1: { progress: 40, message: "Crawled 6 pages" },
    });
    render(<AuditsSection clientId="c1" />);
    expect(screen.getByRole("progressbar", { name: "Audit progress" })).toHaveAttribute(
      "aria-valuenow",
      "40",
    );
    expect(screen.getByText("Crawled 6 pages")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Audit running…" })).toBeDisabled();
    expect(screen.queryByText("/ 100")).not.toBeInTheDocument();
  });

  it("shows an empty bar while the stream has not delivered yet", () => {
    as("manager");
    setAudits([audit({ status: "queued", score: null, summary: null })]);
    render(<AuditsSection clientId="c1" />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });
});

describe("starting and failures", () => {
  it("starts an audit when there is none yet", async () => {
    as("admin");
    setAudits([]);
    start.mockResolvedValue({});
    render(<AuditsSection clientId="c1" />);
    expect(screen.getByText("No audits yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run audit" }));
    expect(start).toHaveBeenCalledOnce();
  });

  it("shows the reason when starting is refused", async () => {
    as("manager");
    start.mockRejectedValue(
      new ApiError(422, "Unprocessable Entity", "Add a website URL to this client before auditing it."),
    );
    render(<AuditsSection clientId="c1" />);
    await userEvent.click(screen.getByRole("button", { name: "Run a new audit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Add a website URL");
  });

  it("shows why the last audit failed instead of a score", () => {
    as("manager");
    setAudits([audit({ status: "failed", score: null, summary: null, error: "The site is unreachable." })]);
    render(<AuditsSection clientId="c1" />);
    expect(screen.getByRole("alert")).toHaveTextContent("The site is unreachable.");
    expect(screen.queryByText("/ 100")).not.toBeInTheDocument();
  });

  it("lets viewers read audits but not start one", () => {
    as("member");
    render(<AuditsSection clientId="c1" />);
    expect(screen.getByText("72")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /audit/i })).not.toBeInTheDocument();
  });
});
