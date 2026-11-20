import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgencySwitcher } from "@/components/shell/agency-switcher";
import { ApiError } from "@/lib/api/problem";
import { useSession } from "@/lib/auth/session-store";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));

const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (m: string) => toastError(m) } }));

// Plain delegates (not vi.fn) where a rejection is possible: see lib/queries/tenants.test.tsx.
let tenantsResult: { data?: { id: string; name: string; role: string }[]; isLoading: boolean } = {
  isLoading: false,
};
vi.mock("@/lib/queries/tenants", () => ({ useTenants: () => tenantsResult }));

const switched: string[] = [];
let switchImpl: (id: string) => Promise<void> = async () => {};
vi.mock("@/lib/api/client", () => ({
  switchTenant: (id: string) => {
    switched.push(id);
    return switchImpl(id);
  },
}));

const two = [
  { id: "t1", name: "Acme", role: "admin" },
  { id: "t2", name: "Globex", role: "manager" },
];

function setup(tenantName = "Acme") {
  useSession.getState().setSession("tok", {
    user_id: "u",
    tenant_id: "t1",
    role: "admin",
    email: "a@b.co",
    tenant_name: tenantName,
  });
  const client = new QueryClient();
  const clear = vi.spyOn(client, "clear");
  render(
    <QueryClientProvider client={client}>
      <AgencySwitcher />
    </QueryClientProvider>,
  );
  return { clear };
}

beforeEach(() => {
  replace.mockReset();
  toastError.mockReset();
  switched.length = 0;
  switchImpl = async () => {};
  tenantsResult = { data: two, isLoading: false };
});

describe("AgencySwitcher", () => {
  it("shows plain text, not a button, when the user has one agency", () => {
    tenantsResult = { data: [two[0]], isLoading: false };
    setup();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows plain text while the agency list is still loading", () => {
    tenantsResult = { isLoading: true };
    setup();
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("lists both agencies with the current one checked when the user has two", async () => {
    setup();
    await userEvent.setup().click(screen.getByRole("button", { name: /Acme/ }));
    expect(await screen.findByRole("menuitemradio", { name: /Acme/ })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("menuitemradio", { name: /Globex/ })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("switches agency, clears every cached query, then goes to the dashboard", async () => {
    const { clear } = setup();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Acme/ }));
    await user.click(await screen.findByRole("menuitemradio", { name: /Globex/ }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(switched).toEqual(["t2"]);
    expect(clear).toHaveBeenCalledTimes(1);
  });

  it("shows the API message and keeps cached data when the switch fails", async () => {
    switchImpl = async () => {
      throw new ApiError(403, "Forbidden", "Not a member of that tenant.");
    };
    const { clear } = setup();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Acme/ }));
    await user.click(await screen.findByRole("menuitemradio", { name: /Globex/ }));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("Not a member of that tenant."));
    expect(clear).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it("truncates a very long agency name instead of breaking the layout", () => {
    tenantsResult = { data: [two[0]], isLoading: false };
    setup("A".repeat(120));
    expect(screen.getByText("A".repeat(120))).toHaveClass("truncate");
  });
});
