import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RoutingSection } from "@/components/ai/routing-section";
import { ApiError } from "@/lib/api/problem";

const connections = [
  { id: "c1", provider: "openai", label: "Prod OpenAI", base_url: null, key_last4: "1234", is_active: true },
  { id: "c2", provider: "anthropic", label: "Claude", base_url: null, key_last4: "9999", is_active: true },
];
let conns: { data?: unknown[]; isLoading: boolean } = { data: connections, isLoading: false };
let routes: { data?: unknown[]; isLoading: boolean } = { data: [], isLoading: false };
const save = vi.fn();
const success = vi.fn();
vi.mock("sonner", () => ({ toast: { success: (...a: unknown[]) => success(...a), error: vi.fn() } }));
vi.mock("@/lib/queries/ai", () => ({
  useAiConnections: () => conns,
  useAiRoutes: () => routes,
  useSaveRoutes: () => ({ mutateAsync: (...a: unknown[]) => save(...a) }),
}));

const strategyRoute = {
  task_type: "strategy",
  connection_id: "c1",
  model: "gpt-4o",
  temperature: 1.2,
  max_tokens: 500,
  fallback_connection_id: null,
  fallback_model: null,
};

beforeEach(() => {
  conns = { data: connections, isLoading: false };
  routes = { data: [], isLoading: false };
  save.mockReset();
  success.mockReset();
});

async function pick(task: string, connection = "c1", model = "gpt-4o") {
  const user = userEvent.setup();
  await user.selectOptions(screen.getByLabelText(`${task} connection`), connection);
  await user.type(screen.getByLabelText(`${task} model`), model);
  return user;
}
const saveBtn = () => screen.getByRole("button", { name: /save routing/i });

describe("RoutingSection", () => {
  it("asks for a connection first when there are none", () => {
    conns = { data: [], isLoading: false };
    render(<RoutingSection testedModels={{}} />);
    expect(screen.getByText(/add a connection first/i)).toBeInTheDocument();
    expect(screen.queryByLabelText("strategy model")).not.toBeInTheDocument();
  });

  it("shows three task rows, prefilled from saved routes and defaults otherwise", () => {
    routes = { data: [strategyRoute], isLoading: false };
    render(<RoutingSection testedModels={{}} />);
    expect(screen.getByLabelText("strategy model")).toHaveValue("gpt-4o");
    expect(screen.getByLabelText("strategy temperature")).toHaveValue(1.2);
    expect(screen.getByLabelText("content model")).toHaveValue("");
    expect(screen.getByLabelText("content temperature")).toHaveValue(0.7);
    expect(screen.getByLabelText("content max tokens")).toHaveValue(2048);
    expect(screen.getByLabelText("analysis connection")).toBeInTheDocument();
  });

  it("suggests tested models for the selected connection but accepts free text", async () => {
    render(<RoutingSection testedModels={{ c1: ["gpt-4o", "gpt-4o-mini"] }} />);
    await pick("strategy", "c1", "my-custom-model");
    const input = screen.getByLabelText("strategy model");
    const options = document.querySelectorAll(`datalist#${input.getAttribute("list")} option`);
    expect([...options].map((o) => o.getAttribute("value"))).toEqual(["gpt-4o", "gpt-4o-mini"]);
    expect(input).toHaveValue("my-custom-model");
  });

  it("sends one PUT with only configured rows and no empty fallback fields", async () => {
    save.mockResolvedValue([]);
    render(<RoutingSection testedModels={{}} />);
    const user = await pick("strategy");
    await user.click(saveBtn());
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith([
      { task_type: "strategy", connection_id: "c1", model: "gpt-4o", temperature: 0.7, max_tokens: 2048 },
    ]);
  });

  it("blocks a temperature above 2 with an inline error", async () => {
    render(<RoutingSection testedModels={{}} />);
    const user = await pick("strategy");
    await user.clear(screen.getByLabelText("strategy temperature"));
    await user.type(screen.getByLabelText("strategy temperature"), "2.5");
    await user.click(saveBtn());
    expect(await screen.findByText("Maximum is 2")).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("blocks max tokens of 0 with an inline error", async () => {
    render(<RoutingSection testedModels={{}} />);
    const user = await pick("strategy");
    await user.clear(screen.getByLabelText("strategy max tokens"));
    await user.type(screen.getByLabelText("strategy max tokens"), "0");
    await user.click(saveBtn());
    expect(await screen.findByText("Minimum is 1")).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("blocks a fallback connection without a fallback model", async () => {
    render(<RoutingSection testedModels={{}} />);
    const user = await pick("strategy");
    await user.selectOptions(screen.getByLabelText("strategy fallback connection"), "c2");
    await user.click(saveBtn());
    expect(
      await screen.findByText("Set both a fallback connection and model, or neither"),
    ).toBeInTheDocument();
    expect(save).not.toHaveBeenCalled();
  });

  it("shows the API detail and keeps the inputs when saving fails", async () => {
    save.mockRejectedValue(new ApiError(404, "Not Found", "AI connection not found."));
    render(<RoutingSection testedModels={{}} />);
    const user = await pick("strategy");
    await user.click(saveBtn());
    expect(await screen.findByText("AI connection not found.")).toBeInTheDocument();
    expect(screen.getByLabelText("strategy model")).toHaveValue("gpt-4o");
  });

  it("toasts on success and disables Save until the form changes again", async () => {
    save.mockResolvedValue([]);
    render(<RoutingSection testedModels={{}} />);
    expect(saveBtn()).toBeDisabled();
    const user = await pick("strategy");
    expect(saveBtn()).toBeEnabled();
    await user.click(saveBtn());
    await waitFor(() => expect(success).toHaveBeenCalled());
    await waitFor(() => expect(saveBtn()).toBeDisabled());
  });
});

describe("RoutingSection after a connection is deleted", () => {
  it("drops the deleted connection from the form so the next save does not send it", async () => {
    save.mockResolvedValue([]);
    routes = {
      data: [
        { ...strategyRoute, task_type: "content", connection_id: "c1", fallback_connection_id: "c2", fallback_model: "claude-x" },
      ],
      isLoading: false,
    };
    const { rerender } = render(<RoutingSection testedModels={{}} />);
    expect(screen.getByLabelText("content connection")).toHaveValue("c1");

    // c1 is deleted: the server drops the route and clears the fallback pointing at it.
    conns = { data: [connections[1]], isLoading: false };
    routes = { data: [], isLoading: false };
    rerender(<RoutingSection testedModels={{}} />);
    expect(screen.getByLabelText("content connection")).toHaveValue("");

    const user = await pick("strategy", "c2", "claude-x");
    await user.click(saveBtn());
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith([
      { task_type: "strategy", connection_id: "c2", model: "claude-x", temperature: 0.7, max_tokens: 2048 },
    ]);
  });
});
