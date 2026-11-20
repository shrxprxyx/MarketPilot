import { render, screen, within } from "@testing-library/react";
import { StatStrip } from "@/components/dashboard/stat-strip";
import type { Role } from "@/lib/auth/session-store";

type Result = { data?: unknown; isLoading?: boolean; isError?: boolean };

// Controllable hook results. The `enabled` flag each hook was called with is recorded,
// because "a role that cannot read this data never fires the request" is the contract.
let clients: Result = {};
let connections: Result = {};
let usage: Result = {};
let members: Result = {};
const enabledArgs: Record<string, boolean | undefined> = {};

vi.mock("@/lib/queries/clients", () => ({ useClients: () => clients }));
vi.mock("@/lib/queries/ai", () => ({
  useAiConnections: (enabled: boolean) => {
    enabledArgs.connections = enabled;
    return connections;
  },
  useAiUsage: (enabled: boolean) => {
    enabledArgs.usage = enabled;
    return usage;
  },
}));
vi.mock("@/lib/queries/members", () => ({
  useMembers: (enabled: boolean) => {
    enabledArgs.members = enabled;
    return members;
  },
}));

const client = (i: number, status = "active") => ({
  id: `c${i}`,
  name: `Client ${i}`,
  website_url: null,
  industry: null,
  goals: null,
  status,
});

beforeEach(() => {
  clients = { data: { items: [client(1), client(2)], next_cursor: null } };
  connections = { data: [{ id: "a", is_active: true }] };
  usage = { data: [] };
  members = { data: [{ id: "m1", status: "active" }] };
  for (const k of Object.keys(enabledArgs)) delete enabledArgs[k];
});

const tile = (name: string) => screen.getByText(name).closest("[data-tile]") as HTMLElement;

describe("StatStrip", () => {
  it("shows an admin all four tiles", () => {
    render(<StatStrip role="admin" />);
    for (const label of ["Clients", "AI models", "Spend · 30d", "Team"]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("shows a manager everything except Team and never asks for members", () => {
    render(<StatStrip role="manager" />);
    expect(screen.getByText("AI models")).toBeInTheDocument();
    expect(screen.getByText("Spend · 30d")).toBeInTheDocument();
    expect(screen.queryByText("Team")).not.toBeInTheDocument();
    expect(enabledArgs).toEqual({ connections: true, usage: true, members: false });
  });

  it("shows a member only Clients and enables no restricted request", () => {
    render(<StatStrip role={"member" as Role} />);
    expect(screen.getByText("Clients")).toBeInTheDocument();
    expect(screen.queryByText("AI models")).not.toBeInTheDocument();
    expect(screen.queryByText("Spend · 30d")).not.toBeInTheDocument();
    expect(screen.queryByText("Team")).not.toBeInTheDocument();
    expect(enabledArgs).toEqual({ connections: false, usage: false, members: false });
  });

  it("counts clients and says how many are active", () => {
    clients = { data: { items: [client(1), client(2, "archived")], next_cursor: null } };
    render(<StatStrip role="admin" />);
    expect(within(tile("Clients")).getByText("2")).toBeInTheDocument();
    expect(within(tile("Clients")).getByText("1 active")).toBeInTheDocument();
  });

  it("shows 100+ when there are more clients than one page", () => {
    const items = Array.from({ length: 100 }, (_, i) => client(i));
    clients = { data: { items, next_cursor: "more" } };
    render(<StatStrip role="admin" />);
    expect(within(tile("Clients")).getByText("100+")).toBeInTheDocument();
  });

  it("shows active connections out of the total", () => {
    connections = {
      data: [
        { id: "a", is_active: true },
        { id: "b", is_active: false },
        { id: "c", is_active: true },
      ],
    };
    render(<StatStrip role="admin" />);
    expect(within(tile("AI models")).getByText("2")).toBeInTheDocument();
    expect(within(tile("AI models")).getByText("of 3 connected")).toBeInTheDocument();
  });

  it("prompts to connect a model when there are none", () => {
    connections = { data: [] };
    render(<StatStrip role="admin" />);
    expect(within(tile("AI models")).getByText("0")).toBeInTheDocument();
    expect(within(tile("AI models")).getByText("Connect a model")).toBeInTheDocument();
  });

  it("sums spend across days and mentions unpriced calls", () => {
    usage = {
      data: [
        { key: "2026-11-19", calls: 10, cost_usd: "1.50", unpriced_calls: 0 },
        { key: "2026-11-20", calls: 2, cost_usd: "0.25", unpriced_calls: 1 },
      ],
    };
    render(<StatStrip role="admin" />);
    expect(within(tile("Spend · 30d")).getByText("$1.75")).toBeInTheDocument();
    expect(within(tile("Spend · 30d")).getByText("12 calls · 1 unpriced")).toBeInTheDocument();
  });

  it("shows $0.00 when nothing has been spent", () => {
    render(<StatStrip role="admin" />);
    expect(within(tile("Spend · 30d")).getByText("$0.00")).toBeInTheDocument();
  });

  it("marks only the failed tile unavailable and still renders the others", () => {
    usage = { isError: true };
    render(<StatStrip role="admin" />);
    expect(within(tile("Spend · 30d")).getByText("Unavailable")).toBeInTheDocument();
    expect(within(tile("Clients")).getByText("2")).toBeInTheDocument();
    expect(within(tile("Team")).getByText("1")).toBeInTheDocument();
  });

  it("shows a skeleton while a tile is loading", () => {
    clients = { isLoading: true };
    render(<StatStrip role="admin" />);
    expect(within(tile("Clients")).getByTestId("stat-skeleton")).toBeInTheDocument();
  });

  it("counts only active team members", () => {
    members = {
      data: [
        { id: "m1", status: "active" },
        { id: "m2", status: "deactivated" },
        { id: "m3", status: "active" },
      ],
    };
    render(<StatStrip role="admin" />);
    expect(within(tile("Team")).getByText("2")).toBeInTheDocument();
  });
});
