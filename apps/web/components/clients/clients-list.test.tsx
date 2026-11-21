import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ClientsList } from "@/components/clients/clients-list";
import { ApiError } from "@/lib/api/problem";
import { useSession, type Role } from "@/lib/auth/session-store";

const client = (over = {}) => ({
  id: "c1",
  name: "Acme Pets",
  website_url: "https://acme.example",
  industry: "Pet food",
  goals: null,
  status: "active",
  ...over,
});

let list: {
  data?: { items: unknown[]; next_cursor: string | null };
  isLoading: boolean;
  isError: boolean;
} = { data: { items: [client()], next_cursor: null }, isLoading: false, isError: false };
const create = vi.fn();
const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/queries/clients", () => ({
  useClients: () => list,
  useCreateClient: () => ({ mutateAsync: (...a: unknown[]) => create(...a) }),
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
  list = { data: { items: [client()], next_cursor: null }, isLoading: false, isError: false };
  create.mockReset();
  push.mockReset();
  useSession.getState().clear();
});

describe("ClientsList", () => {
  it("shows name, industry and status, linking to the client page", () => {
    as("manager");
    render(<ClientsList />);
    const link = screen.getByRole("link", { name: /acme pets/i });
    expect(link).toHaveAttribute("href", "/clients/c1");
    expect(within(link).getByText("Pet food")).toBeInTheDocument();
    expect(within(link).getByText("active")).toBeInTheDocument();
  });

  it("shows skeletons while loading", () => {
    as("manager");
    list = { isLoading: true, isError: false };
    render(<ClientsList />);
    expect(screen.getAllByTestId("client-skeleton").length).toBeGreaterThan(0);
  });

  it("shows an error message when loading fails", () => {
    as("manager");
    list = { isLoading: false, isError: true };
    render(<ClientsList />);
    expect(screen.getByText(/couldn.t load clients/i)).toBeInTheDocument();
  });

  it("notes when only the first 100 clients are shown", () => {
    as("manager");
    list = { data: { items: [client()], next_cursor: "abc" }, isLoading: false, isError: false };
    render(<ClientsList />);
    expect(screen.getByText("Showing the first 100 clients")).toBeInTheDocument();
  });

  it("empty state offers New client to managers", () => {
    as("manager");
    list = { data: { items: [], next_cursor: null }, isLoading: false, isError: false };
    render(<ClientsList />);
    expect(screen.getByText(/no clients yet/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New client" }).length).toBeGreaterThan(0);
  });

  it("empty state is plain text for members and there is no New client button", () => {
    as("member");
    list = { data: { items: [], next_cursor: null }, isLoading: false, isError: false };
    render(<ClientsList />);
    expect(screen.getByText(/no clients yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New client" })).not.toBeInTheDocument();
  });

  it("hides New client from members even when clients exist", () => {
    as("member");
    render(<ClientsList />);
    expect(screen.queryByRole("button", { name: "New client" })).not.toBeInTheDocument();
  });
});

describe("New client dialog", () => {
  async function open() {
    as("admin");
    render(<ClientsList />);
    await userEvent.click(screen.getAllByRole("button", { name: "New client" })[0]);
    return within(await screen.findByRole("dialog"));
  }

  it("requires a name and sends nothing without it", async () => {
    const dialog = await open();
    await userEvent.click(dialog.getByRole("button", { name: "Create client" }));
    expect(await dialog.findByText("Name is required")).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it("rejects a website that is not http(s)", async () => {
    const dialog = await open();
    await userEvent.type(dialog.getByLabelText("Name"), "Acme");
    await userEvent.type(dialog.getByLabelText("Website (optional)"), "acme.example");
    await userEvent.click(dialog.getByRole("button", { name: "Create client" }));
    expect(await dialog.findByText("Website must start with http:// or https://")).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it("creates with only the filled fields and opens the new client's page", async () => {
    create.mockResolvedValue({ id: "new1", name: "Acme" });
    const dialog = await open();
    await userEvent.type(dialog.getByLabelText("Name"), "Acme");
    await userEvent.click(dialog.getByRole("button", { name: "Create client" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ name: "Acme" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/clients/new1"));
  });

  it("includes website and industry when filled", async () => {
    create.mockResolvedValue({ id: "new1", name: "Acme" });
    const dialog = await open();
    await userEvent.type(dialog.getByLabelText("Name"), "Acme");
    await userEvent.type(dialog.getByLabelText("Website (optional)"), "https://acme.example");
    await userEvent.type(dialog.getByLabelText("Industry (optional)"), "Pets");
    await userEvent.click(dialog.getByRole("button", { name: "Create client" }));
    await waitFor(() =>
      expect(create).toHaveBeenCalledWith({
        name: "Acme",
        website_url: "https://acme.example",
        industry: "Pets",
      }),
    );
  });

  it("keeps the dialog open with input retained and shows the detail when create fails", async () => {
    create.mockRejectedValue(new ApiError(403, "Forbidden", "You cannot create clients."));
    const dialog = await open();
    await userEvent.type(dialog.getByLabelText("Name"), "Acme");
    await userEvent.click(dialog.getByRole("button", { name: "Create client" }));
    expect(await dialog.findByText("You cannot create clients.")).toBeInTheDocument();
    expect(dialog.getByLabelText("Name")).toHaveValue("Acme");
    expect(push).not.toHaveBeenCalled();
  });
});
