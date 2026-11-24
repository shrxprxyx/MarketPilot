import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GettingStarted } from "@/components/dashboard/getting-started";

type Result = { data?: unknown; isLoading?: boolean; isError?: boolean };
let clients: Result = {};
let connections: Result = {};
let usage: Result = {};
const enabled: { connections: boolean[]; usage: boolean[] } = { connections: [], usage: [] };

vi.mock("@/lib/queries/clients", () => ({ useClients: () => clients }));
vi.mock("@/lib/queries/ai", () => ({
  useAiConnections: (on: boolean) => {
    enabled.connections.push(on);
    return connections;
  },
  useAiUsage: (on: boolean) => {
    enabled.usage.push(on);
    return usage;
  },
}));

const client = { id: "c1", name: "Bloom", status: "active" };
const row = (calls: number) => ({ key: "2026-11-20", calls, cost_usd: "0", unpriced_calls: 0 });

beforeEach(() => {
  window.localStorage.clear();
  clients = { data: { items: [], next_cursor: null } };
  connections = { data: [] };
  usage = { data: [] };
  enabled.connections.length = 0;
  enabled.usage.length = 0;
});

describe("GettingStarted", () => {
  it("starts with the agency done and points at adding a client", () => {
    render(<GettingStarted role="admin" />);
    expect(screen.getByText("1 of 4 done")).toBeInTheDocument();
    expect(screen.getByText(/create your agency/i)).toHaveTextContent("(done)");
    expect(screen.getByText(/add your first client/i)).toHaveTextContent("(not done yet)");
    // Only the next step gets a call to action.
    expect(screen.getByRole("link", { name: "Add a client" })).toHaveAttribute("href", "/clients");
    expect(screen.queryByRole("link", { name: "Connect a model" })).not.toBeInTheDocument();
  });

  it("advances as steps are completed", () => {
    clients = { data: { items: [client], next_cursor: null } };
    render(<GettingStarted role="manager" />);
    expect(screen.getByText("2 of 4 done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect a model" })).toHaveAttribute(
      "href",
      "/settings/ai",
    );
  });

  it("sends the last step to the first client", () => {
    clients = { data: { items: [client], next_cursor: null } };
    connections = { data: [{ id: "k1" }] };
    render(<GettingStarted role="admin" />);
    expect(screen.getByText("3 of 4 done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open a client" })).toHaveAttribute(
      "href",
      "/clients/c1",
    );
  });

  it("disappears once everything is done", () => {
    clients = { data: { items: [client], next_cursor: null } };
    connections = { data: [{ id: "k1" }] };
    usage = { data: [row(3)] };
    const { container } = render(<GettingStarted role="admin" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("is not shown to members, who cannot do any of the steps", () => {
    const { container } = render(<GettingStarted role="member" />);
    expect(container).toBeEmptyDOMElement();
    expect(enabled.connections.every((f) => f === false)).toBe(true);
    expect(enabled.usage.every((f) => f === false)).toBe(true);
  });

  it("shows nothing while loading or when a request failed", () => {
    clients = { isLoading: true };
    const { container, rerender } = render(<GettingStarted role="admin" />);
    expect(container).toBeEmptyDOMElement();
    clients = { data: { items: [], next_cursor: null } };
    usage = { isError: true };
    rerender(<GettingStarted role="admin" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("can be dismissed, and stays dismissed", async () => {
    const { unmount } = render(<GettingStarted role="admin" />);
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(/getting started/i)).not.toBeInTheDocument();
    unmount();
    const { container } = render(<GettingStarted role="admin" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("still works when browser storage is unavailable", async () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    try {
      render(<GettingStarted role="admin" />);
      expect(screen.getByText("1 of 4 done")).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
      expect(screen.queryByText("1 of 4 done")).not.toBeInTheDocument();
    } finally {
      get.mockRestore();
      set.mockRestore();
    }
  });
});
