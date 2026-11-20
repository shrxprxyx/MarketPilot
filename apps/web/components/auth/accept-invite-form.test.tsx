import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AcceptInviteForm } from "@/components/auth/accept-invite-form";

let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(search),
}));

const signIn = vi.fn();
vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/client")>("@/lib/api/client");
  return { ...actual, signIn: (...a: unknown[]) => signIn(...a) };
});

beforeEach(() => {
  signIn.mockReset();
  search = "";
});

describe("AcceptInviteForm", () => {
  it("shows an invalid-link state and no form when the token is missing", () => {
    render(<AcceptInviteForm />);
    expect(screen.getByText("This invite link is invalid")).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(signIn).not.toHaveBeenCalled();
  });

  it("sends the token and password", async () => {
    signIn.mockResolvedValue(undefined);
    search = "token=abc123";
    const user = userEvent.setup();
    render(<AcceptInviteForm />);
    await user.type(screen.getByLabelText("Password"), "correct-horse-1");
    await user.click(screen.getByRole("button", { name: /join/i }));
    await vi.waitFor(() =>
      expect(signIn).toHaveBeenCalledWith("accept-invite", { token: "abc123", password: "correct-horse-1" }),
    );
  });

  it("blocks a password under 10 characters", async () => {
    search = "token=abc123";
    const user = userEvent.setup();
    render(<AcceptInviteForm />);
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: /join/i }));
    expect(await screen.findByText("Use at least 10 characters")).toBeInTheDocument();
    expect(signIn).not.toHaveBeenCalled();
  });
});
