import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UserMenu } from "@/components/shell/user-menu";
import { useSession } from "@/lib/auth/session-store";

const signedOut: number[] = [];
vi.mock("@/lib/api/client", () => ({
  signOut: async () => {
    signedOut.push(1);
  },
}));

beforeEach(() => {
  signedOut.length = 0;
  useSession.getState().setSession("tok", {
    user_id: "u",
    tenant_id: "t1",
    role: "manager",
    email: "jane@acme.co",
    tenant_name: "Acme",
  });
});

describe("UserMenu", () => {
  it("shows the signed-in email and role on the trigger", () => {
    render(<UserMenu />);
    const trigger = screen.getByRole("button", { name: /jane@acme\.co/ });
    expect(trigger).toHaveTextContent("manager");
  });

  it("signs out from the menu", async () => {
    render(<UserMenu />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /jane@acme\.co/ }));
    await user.click(await screen.findByRole("menuitem", { name: /Sign out/ }));
    expect(signedOut).toHaveLength(1);
  });
});
