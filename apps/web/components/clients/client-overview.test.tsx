import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ClientOverview } from "@/components/clients/client-overview";
import { ApiError } from "@/lib/api/problem";
import { useSession, type Role } from "@/lib/auth/session-store";

const client = (over = {}) => ({
  id: "c1",
  name: "Acme Pets",
  website_url: "https://acme.example",
  industry: "Pet food",
  goals: ["Grow", "Hire"],
  status: "active",
  ...over,
});

const update = vi.fn();
const archive = vi.fn();
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/queries/clients", () => ({
  useUpdateClient: () => ({ mutateAsync: (...a: unknown[]) => update(...a) }),
  useArchiveClient: () => ({ mutateAsync: (...a: unknown[]) => archive(...a) }),
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
  update.mockReset();
  archive.mockReset();
  useSession.getState().clear();
});

describe("ClientOverview", () => {
  it("shows the details, with the website as a safe external link", () => {
    as("manager");
    render(<ClientOverview client={client()} />);
    expect(screen.getByText("Pet food")).toBeInTheDocument();
    expect(screen.getByText("Grow")).toBeInTheDocument();
    expect(screen.getByText("Hire")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "https://acme.example" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("shows placeholders for missing details", () => {
    as("manager");
    render(<ClientOverview client={client({ website_url: null, industry: null, goals: null })} />);
    expect(screen.getByText("No website")).toBeInTheDocument();
    expect(screen.getByText("No industry set")).toBeInTheDocument();
    expect(screen.getByText("No goals yet")).toBeInTheDocument();
  });

  it("gives members no action buttons", () => {
    as("member");
    render(<ClientOverview client={client()} />);
    for (const name of ["Edit client", "Archive", "Restore"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });

  it("offers Edit and Archive, not Restore, for an active client", () => {
    as("manager");
    render(<ClientOverview client={client()} />);
    expect(screen.getByRole("button", { name: "Edit client" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Archive" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restore" })).not.toBeInTheDocument();
  });

  it("offers Restore, not Archive, for an archived client", () => {
    as("admin");
    render(<ClientOverview client={client({ status: "archived" })} />);
    expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
  });

  it("archives only after confirming, and the confirmation says it can be restored", async () => {
    as("manager");
    archive.mockResolvedValue(undefined);
    render(<ClientOverview client={client()} />);
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByText(/can be restored/i)).toBeInTheDocument();
    expect(archive).not.toHaveBeenCalled();
    await userEvent.click(dialog.getByRole("button", { name: "Archive client" }));
    await waitFor(() => expect(archive).toHaveBeenCalledTimes(1));
  });

  it("shows the API detail when archiving is rejected", async () => {
    as("manager");
    archive.mockRejectedValue(new ApiError(403, "Forbidden", "Not allowed."));
    render(<ClientOverview client={client()} />);
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    await userEvent.click(await screen.findByRole("button", { name: "Archive client" }));
    expect(await screen.findByText("Not allowed.")).toBeInTheDocument();
  });

  it("restores with an update to active, and shows the detail if it fails", async () => {
    as("manager");
    update.mockRejectedValueOnce(new ApiError(500, "Error", "Could not restore."));
    render(<ClientOverview client={client({ status: "archived" })} />);
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(update).toHaveBeenCalledWith({ status: "active" });
    expect(await screen.findByText("Could not restore.")).toBeInTheDocument();
  });
});

describe("Edit client dialog", () => {
  async function open(over = {}) {
    as("manager");
    render(<ClientOverview client={client(over)} />);
    await userEvent.click(screen.getByRole("button", { name: "Edit client" }));
    return within(await screen.findByRole("dialog"));
  }

  it("is prefilled from the client", async () => {
    const dialog = await open();
    expect(dialog.getByLabelText("Name")).toHaveValue("Acme Pets");
    expect(dialog.getByLabelText("Website (optional)")).toHaveValue("https://acme.example");
    expect(dialog.getByLabelText("Industry (optional)")).toHaveValue("Pet food");
    expect(dialog.getByLabelText("Goals (one per line)")).toHaveValue("Grow\nHire");
  });

  it("requires a name and sends nothing without it", async () => {
    const dialog = await open();
    await userEvent.clear(dialog.getByLabelText("Name"));
    await userEvent.click(dialog.getByRole("button", { name: "Save changes" }));
    expect(await dialog.findByText("Name is required")).toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
  });

  it("rejects a website that is not http(s)", async () => {
    const dialog = await open();
    await userEvent.clear(dialog.getByLabelText("Website (optional)"));
    await userEvent.type(dialog.getByLabelText("Website (optional)"), "acme.example");
    await userEvent.click(dialog.getByRole("button", { name: "Save changes" }));
    expect(await dialog.findByText("Website must start with http:// or https://")).toBeInTheDocument();
    expect(update).not.toHaveBeenCalled();
  });

  it("sends cleared fields as null so the value is really removed, and trims goals", async () => {
    update.mockResolvedValue({});
    const dialog = await open();
    await userEvent.clear(dialog.getByLabelText("Industry (optional)"));
    await userEvent.clear(dialog.getByLabelText("Website (optional)"));
    const goals = dialog.getByLabelText("Goals (one per line)");
    await userEvent.clear(goals);
    await userEvent.type(goals, "Launch{Enter}{Enter}  Scale  ");
    await userEvent.click(dialog.getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        name: "Acme Pets",
        website_url: null,
        industry: null,
        goals: ["Launch", "Scale"],
      }),
    );
  });

  it("sends goals as null when every line is cleared", async () => {
    update.mockResolvedValue({});
    const dialog = await open();
    await userEvent.clear(dialog.getByLabelText("Goals (one per line)"));
    await userEvent.click(dialog.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(update.mock.calls[0][0].goals).toBeNull();
  });

  it("keeps the dialog open with the detail shown when saving fails", async () => {
    update.mockRejectedValue(new ApiError(422, "Unprocessable", "Name already used."));
    const dialog = await open();
    await userEvent.clear(dialog.getByLabelText("Name"));
    await userEvent.type(dialog.getByLabelText("Name"), "Renamed");
    await userEvent.click(dialog.getByRole("button", { name: "Save changes" }));
    expect(await dialog.findByText("Name already used.")).toBeInTheDocument();
    expect(dialog.getByLabelText("Name")).toHaveValue("Renamed");
  });
});
