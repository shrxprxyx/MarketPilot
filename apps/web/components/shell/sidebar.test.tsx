import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Sidebar } from "@/components/shell/sidebar";
import { useSession, type Role } from "@/lib/auth/session-store";

let pathname = "/";
vi.mock("next/navigation", () => ({ usePathname: () => pathname }));

function signInAs(role: Role) {
  useSession.getState().setSession("tok", {
    user_id: "u",
    tenant_id: "t1",
    role,
    email: "a@b.co",
    tenant_name: "Acme",
  });
}

beforeEach(() => {
  pathname = "/";
});

describe("Sidebar", () => {
  it("shows a member only Dashboard and Clients", () => {
    signInAs("member");
    render(<Sidebar />);
    expect(screen.getByRole("link", { name: /Dashboard/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Clients/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Team/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /AI models/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Usage/ })).not.toBeInTheDocument();
  });

  it("shows an admin all five items, numbered 01 to 05, under both section labels", () => {
    signInAs("admin");
    render(<Sidebar />);
    for (const n of ["01", "02", "03", "04", "05"]) {
      expect(screen.getByText(n)).toBeInTheDocument();
    }
    expect(screen.getByText("A · WORKSPACE")).toBeInTheDocument();
    expect(screen.getByText("B · AI")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Team/ })).toHaveAttribute("href", "/team");
  });

  it("marks the parent item current on a nested route", () => {
    signInAs("admin");
    pathname = "/clients/123";
    render(<Sidebar />);
    expect(screen.getByRole("link", { name: /Clients/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /Dashboard/ })).not.toHaveAttribute("aria-current");
  });

  it("calls onNavigate when a link is clicked", async () => {
    signInAs("admin");
    const onNavigate = vi.fn();
    render(<Sidebar onNavigate={onNavigate} />);
    await userEvent.setup().click(screen.getByRole("link", { name: /Clients/ }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });
});
