import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TeamPage } from "@/components/team/team-page";
import { ApiError } from "@/lib/api/problem";

let role: "admin" | "manager" | "member" = "admin";
vi.mock("@/lib/auth/session-store", () => ({
  useSession: (sel: (s: unknown) => unknown) =>
    sel({ me: { user_id: "u1", role, email: "a@x.com", tenant_id: "t", tenant_name: "T" } }),
}));

const member = (over = {}) => ({
  id: "m1",
  user_id: "u1",
  email: "a@x.com",
  role: "admin",
  status: "active",
  created_at: "2026-11-01T00:00:00Z",
  ...over,
});
let members: { data?: unknown[]; isLoading: boolean; isError: boolean };
let invites: { data?: unknown[]; isError: boolean };
const invite = vi.fn();
const update = vi.fn();
const revoke = vi.fn();
const membersEnabled = vi.fn();
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/queries/members", () => ({
  useMembers: (enabled: boolean) => {
    membersEnabled(enabled);
    return members;
  },
  usePendingInvites: () => invites,
  useInviteMember: () => ({ mutateAsync: (...a: unknown[]) => invite(...a), isPending: false }),
  useUpdateMember: () => ({ mutateAsync: (...a: unknown[]) => update(...a), isPending: false }),
  useRevokeInvite: () => ({ mutateAsync: (...a: unknown[]) => revoke(...a), isPending: false }),
}));

beforeEach(() => {
  role = "admin";
  members = {
    data: [member(), member({ id: "m2", user_id: "u2", email: "b@x.com", role: "member" })],
    isLoading: false,
    isError: false,
  };
  invites = { data: [], isError: false };
  [invite, update, revoke, membersEnabled].forEach((m) => m.mockReset());
});

describe("TeamPage", () => {
  it("lists members and marks the current user", () => {
    render(<TeamPage />);
    expect(screen.getByText("a@x.com")).toBeInTheDocument();
    expect(screen.getByText("(you)")).toBeInTheDocument();
    expect(screen.getByText("b@x.com")).toBeInTheDocument();
  });

  it("does not request members for non-admins and explains why", () => {
    role = "manager";
    render(<TeamPage />);
    expect(membersEnabled).toHaveBeenCalledWith(false);
    expect(screen.getByText(/only admins can manage the team/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /invite member/i })).not.toBeInTheDocument();
  });

  it("changes a member's role", async () => {
    update.mockResolvedValue({});
    render(<TeamPage />);
    await userEvent.selectOptions(screen.getByLabelText("Role for b@x.com"), "manager");
    expect(update).toHaveBeenCalledWith({ id: "m2", patch: { role: "manager" } });
  });

  it("shows the server error when the last admin cannot be deactivated", async () => {
    update.mockRejectedValue(
      new ApiError(409, "Conflict", "The last admin of a tenant cannot be demoted or deactivated."),
    );
    render(<TeamPage />);
    await userEvent.click(screen.getAllByRole("button", { name: "Deactivate" })[0]);
    expect(update).toHaveBeenCalledWith({ id: "m1", patch: { status: "deactivated" } });
    expect(await screen.findByText(/last admin/i)).toBeInTheDocument();
  });

  it("creates an invite and shows the copyable link", async () => {
    invite.mockResolvedValue({
      id: "i1",
      email: "n@x.com",
      role: "manager",
      invite_token: "tok123",
      expires_at: "",
    });
    render(<TeamPage />);
    await userEvent.click(screen.getByRole("button", { name: /invite member/i }));
    await userEvent.type(screen.getByLabelText("Email"), "n@x.com");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "manager");
    await userEvent.click(screen.getByRole("button", { name: /create invite/i }));
    expect(invite).toHaveBeenCalledWith({ email: "n@x.com", role: "manager" });
    const field = await screen.findByLabelText("Invite link");
    expect((field as HTMLInputElement).value).toMatch(/\/accept-invite\?token=tok123$/);
  });

  it("revokes a pending invite", async () => {
    invites = {
      data: [{ id: "i1", email: "p@x.com", role: "member", expires_at: "", created_at: "" }],
      isError: false,
    };
    revoke.mockResolvedValue(undefined);
    render(<TeamPage />);
    await userEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("i1"));
  });
});
