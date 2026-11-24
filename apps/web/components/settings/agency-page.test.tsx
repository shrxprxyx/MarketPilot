import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgencyPage } from "@/components/settings/agency-page";
import { ApiError } from "@/lib/api/problem";
import { useSession, type Role } from "@/lib/auth/session-store";

const tenant = (over = {}) => ({
  id: "t",
  name: "Acme Agency",
  slug: "acme-agency",
  plan: "free",
  branding: { logo_url: null as string | null, primary_color: null as string | null, report_footer: null as string | null },
  ...over,
});

let state: { data?: ReturnType<typeof tenant>; isLoading: boolean; isError: boolean } = {
  data: tenant(),
  isLoading: false,
  isError: false,
};
const rename = vi.fn();
const saveBranding = vi.fn();
const enabledFlags: boolean[] = [];
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/queries/tenant", () => ({
  useTenantDetail: (enabled: boolean) => {
    enabledFlags.push(enabled);
    return state;
  },
  useRenameTenant: () => ({ mutateAsync: (...a: unknown[]) => rename(...a) }),
  useSaveBranding: () => ({ mutateAsync: (...a: unknown[]) => saveBranding(...a) }),
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
  state = { data: tenant(), isLoading: false, isError: false };
  rename.mockReset();
  saveBranding.mockReset();
  enabledFlags.length = 0;
  useSession.getState().clear();
});

describe("AgencyPage", () => {
  it("lets an admin rename the agency", async () => {
    as("admin");
    rename.mockResolvedValue(tenant({ name: "Acme Studio" }));
    render(<AgencyPage />);
    const input = screen.getByLabelText("Agency name");
    expect(input).toHaveValue("Acme Agency");
    expect(screen.getByRole("button", { name: "Save name" })).toBeDisabled(); // nothing changed
    await userEvent.clear(input);
    await userEvent.type(input, "  Acme Studio ");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));
    expect(rename).toHaveBeenCalledWith("Acme Studio");
  });

  it("rejects a blank name without calling the API", async () => {
    as("admin");
    render(<AgencyPage />);
    await userEvent.clear(screen.getByLabelText("Agency name"));
    await userEvent.type(screen.getByLabelText("Agency name"), "   ");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));
    expect(await screen.findByText("Agency name is required")).toBeInTheDocument();
    expect(rename).not.toHaveBeenCalled();
  });

  it("saves branding, sending blank fields as null", async () => {
    as("admin");
    saveBranding.mockResolvedValue(tenant());
    render(<AgencyPage />);
    await userEvent.type(screen.getByLabelText("Logo URL (optional)"), "https://cdn.example.com/l.png");
    await userEvent.type(screen.getByLabelText("Primary color (optional)"), "#1F6F43");
    await userEvent.click(screen.getByRole("button", { name: "Save branding" }));
    expect(saveBranding).toHaveBeenCalledWith({
      logo_url: "https://cdn.example.com/l.png",
      primary_color: "#1F6F43",
      report_footer: null,
    });
  });

  it("shows the saved branding and previews the color", () => {
    as("admin");
    state = {
      data: tenant({
        branding: { logo_url: "https://x.co/l.png", primary_color: "#112233", report_footer: "Hi" },
      }),
      isLoading: false,
      isError: false,
    };
    render(<AgencyPage />);
    expect(screen.getByLabelText("Logo URL (optional)")).toHaveValue("https://x.co/l.png");
    expect(screen.getByLabelText("Report footer (optional)")).toHaveValue("Hi");
    expect(screen.getByTestId("color-swatch")).toHaveStyle({ backgroundColor: "#112233" });
  });

  it.each([
    ["javascript:alert(1)", "Logo URL (optional)", "Logo URL must start with http:// or https://"],
    ["green", "Primary color (optional)", "Use a hex color like #1f6f43"],
  ])("rejects %s before it reaches the API", async (value, label, message) => {
    as("admin");
    render(<AgencyPage />);
    await userEvent.type(screen.getByLabelText(label), value);
    await userEvent.click(screen.getByRole("button", { name: "Save branding" }));
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(saveBranding).not.toHaveBeenCalled();
  });

  it("shows the server's message when saving fails", async () => {
    as("admin");
    rename.mockRejectedValue(new ApiError(422, "Unprocessable Entity", "Name cannot be blank."));
    render(<AgencyPage />);
    await userEvent.type(screen.getByLabelText("Agency name"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Save name" }));
    expect(await screen.findByText("Name cannot be blank.")).toBeInTheDocument();
  });

  it("tells managers and members it is admin only, without requesting the data", () => {
    for (const role of ["manager", "member"] as const) {
      as(role);
      const { unmount } = render(<AgencyPage />);
      expect(screen.getByText("Only admins can change agency settings.")).toBeInTheDocument();
      expect(screen.queryByLabelText("Agency name")).not.toBeInTheDocument();
      unmount();
    }
    expect(enabledFlags.every((f) => f === false)).toBe(true);
  });

  it("shows a skeleton while loading and a message on error", () => {
    as("admin");
    state = { isLoading: true, isError: false };
    const { unmount } = render(<AgencyPage />);
    expect(screen.getByTestId("agency-skeleton")).toBeInTheDocument();
    unmount();
    state = { isLoading: false, isError: true };
    render(<AgencyPage />);
    expect(screen.getByText(/couldn't load the agency settings/i)).toBeInTheDocument();
  });
});
