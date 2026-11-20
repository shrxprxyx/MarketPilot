import { render, screen, waitFor } from "@testing-library/react";
import { SessionGate } from "@/components/session-gate";
import { useSession } from "@/lib/auth/session-store";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/clients",
}));

const refreshSession = vi.fn();
vi.mock("@/lib/api/client", () => ({ refreshSession: () => refreshSession() }));

beforeEach(() => {
  replace.mockReset();
  refreshSession.mockReset();
  useSession.getState().clear();
  useSession.setState({ status: "unknown" });
});

describe("SessionGate", () => {
  it("shows a skeleton and hides children while the session is unknown", () => {
    refreshSession.mockReturnValue(new Promise(() => {}));
    render(
      <SessionGate>
        <p>secret</p>
      </SessionGate>,
    );
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
    expect(screen.getByTestId("session-skeleton")).toBeInTheDocument();
  });

  it("redirects to /login with the current path when refresh fails", async () => {
    refreshSession.mockImplementation(async () => {
      useSession.getState().clear();
      return false;
    });
    render(
      <SessionGate>
        <p>secret</p>
      </SessionGate>,
    );
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?next=%2Fclients"));
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("renders children once authenticated, without refreshing again", () => {
    useSession.getState().setSession("tok", {
      user_id: "u",
      tenant_id: "t",
      role: "admin",
      email: "a@b.co",
      tenant_name: "Acme",
    });
    render(
      <SessionGate>
        <p>secret</p>
      </SessionGate>,
    );
    expect(screen.getByText("secret")).toBeInTheDocument();
    expect(refreshSession).not.toHaveBeenCalled();
  });
});
