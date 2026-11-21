import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConnectionsSection } from "@/components/ai/connections-section";
import { ApiError } from "@/lib/api/problem";

const conn = (over = {}) => ({
  id: "c1",
  provider: "openai",
  label: "Prod OpenAI",
  base_url: null,
  key_last4: "1234",
  is_active: true,
  ...over,
});

let list: { data?: unknown[]; isLoading: boolean; isError: boolean } = {
  data: [conn()],
  isLoading: false,
  isError: false,
};
const create = vi.fn();
const test = vi.fn();
const del = vi.fn();
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/lib/queries/ai", () => ({
  useAiConnections: () => list,
  useCreateConnection: () => ({ mutateAsync: (...a: unknown[]) => create(...a) }),
  useTestConnection: () => ({ mutateAsync: (...a: unknown[]) => test(...a) }),
  useDeleteConnection: () => ({ mutateAsync: (...a: unknown[]) => del(...a) }),
}));

const onTested = vi.fn();
const renderIt = (testedModels: Record<string, string[]> = {}) =>
  render(<ConnectionsSection testedModels={testedModels} onTested={onTested} />);

beforeEach(() => {
  list = { data: [conn()], isLoading: false, isError: false };
  [create, test, del, onTested].forEach((m) => m.mockReset());
});

describe("ConnectionsSection list", () => {
  it("shows provider, label and masked key for each connection", () => {
    renderIt();
    expect(screen.getByText("Prod OpenAI")).toBeInTheDocument();
    expect(screen.getByText("••••1234")).toBeInTheDocument();
    expect(screen.getByText(/openai/i, { selector: "[data-provider]" })).toBeInTheDocument();
  });

  it("shows skeletons while loading", () => {
    list = { isLoading: true, isError: false };
    renderIt();
    expect(screen.getAllByTestId("connection-skeleton").length).toBeGreaterThan(0);
  });

  it("shows an empty state with an add action", () => {
    list = { data: [], isLoading: false, isError: false };
    renderIt();
    expect(screen.getByText(/no connections yet/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /add connection/i }).length).toBeGreaterThan(0);
  });
});

describe("test and delete", () => {
  it("reports the model count and passes models up after a successful test", async () => {
    test.mockResolvedValue({ ok: true, models: ["a", "b"] });
    renderIt({ c1: ["a", "b"] });
    await userEvent.click(screen.getByRole("button", { name: "Test Prod OpenAI" }));
    expect(test).toHaveBeenCalledWith("c1");
    await waitFor(() => expect(onTested).toHaveBeenCalledWith("c1", ["a", "b"]));
    expect(screen.getByText(/2 models/i)).toBeInTheDocument();
  });

  it("shows the API detail inside the row when a test fails", async () => {
    test.mockRejectedValue(new ApiError(502, "Bad Gateway", "Invalid API key."));
    renderIt();
    await userEvent.click(screen.getByRole("button", { name: "Test Prod OpenAI" }));
    expect(await screen.findByText("Invalid API key.")).toBeInTheDocument();
    expect(screen.getByText("Prod OpenAI")).toBeInTheDocument();
  });

  it("deletes only after the user confirms", async () => {
    del.mockResolvedValue(undefined);
    renderIt();
    await userEvent.click(screen.getByRole("button", { name: "Delete Prod OpenAI" }));
    expect(del).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Delete connection" }));
    expect(del).toHaveBeenCalledWith("c1");
  });

  it("shows the API detail and keeps the row when a delete is rejected", async () => {
    del.mockRejectedValue(new ApiError(409, "Conflict", "Connection is used by a route."));
    renderIt();
    await userEvent.click(screen.getByRole("button", { name: "Delete Prod OpenAI" }));
    await userEvent.click(screen.getByRole("button", { name: "Delete connection" }));
    expect(await screen.findByText("Connection is used by a route.")).toBeInTheDocument();
    expect(screen.getByText("Prod OpenAI")).toBeInTheDocument();
  });
});

describe("add connection dialog", () => {
  async function open() {
    renderIt();
    await userEvent.click(screen.getAllByRole("button", { name: /add connection/i })[0]);
    return within(await screen.findByRole("dialog"));
  }

  it("hides the key field and shows the tunnel help for ollama", async () => {
    const dialog = await open();
    await userEvent.selectOptions(dialog.getByLabelText("Provider"), "ollama");
    expect(dialog.queryByLabelText("API key")).not.toBeInTheDocument();
    expect(dialog.getByText(/localhost/i)).toBeInTheDocument();
    expect(dialog.getByText(/tunnel/i)).toBeInTheDocument();
  });

  it("requires a base URL for ollama and sends nothing without it", async () => {
    const dialog = await open();
    await userEvent.selectOptions(dialog.getByLabelText("Provider"), "ollama");
    await userEvent.type(dialog.getByLabelText("Name"), "Local");
    await userEvent.click(dialog.getByRole("button", { name: "Save connection" }));
    expect(await dialog.findByText("Base URL is required for this provider")).toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it("creates an openai connection with provider, label and key only, then closes", async () => {
    create.mockResolvedValue(conn());
    const dialog = await open();
    await userEvent.type(dialog.getByLabelText("Name"), "Work");
    await userEvent.type(dialog.getByLabelText("API key"), "sk-abcd1234");
    await userEvent.click(dialog.getByRole("button", { name: "Save connection" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create).toHaveBeenCalledWith({ provider: "openai", label: "Work", api_key: "sk-abcd1234" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("does not send a base URL typed under another provider after switching to anthropic", async () => {
    create.mockResolvedValue(conn());
    const dialog = await open();
    await userEvent.selectOptions(dialog.getByLabelText("Provider"), "openai_compatible");
    await userEvent.type(dialog.getByLabelText("Base URL"), "https://evil.example");
    await userEvent.selectOptions(dialog.getByLabelText("Provider"), "anthropic");
    await userEvent.type(dialog.getByLabelText("Name"), "Claude");
    await userEvent.type(dialog.getByLabelText("API key"), "sk-abcd1234");
    await userEvent.click(dialog.getByRole("button", { name: "Save connection" }));
    await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
    expect(create).toHaveBeenCalledWith({ provider: "anthropic", label: "Claude", api_key: "sk-abcd1234" });
  });

  it("keeps the dialog open with input retained and shows the detail when create fails", async () => {
    create.mockRejectedValue(new ApiError(422, "Unprocessable", "Label already in use."));
    const dialog = await open();
    await userEvent.type(dialog.getByLabelText("Name"), "Work");
    await userEvent.type(dialog.getByLabelText("API key"), "sk-abcd1234");
    await userEvent.click(dialog.getByRole("button", { name: "Save connection" }));
    expect(await dialog.findByText("Label already in use.")).toBeInTheDocument();
    expect(dialog.getByLabelText("Name")).toHaveValue("Work");
  });
});
