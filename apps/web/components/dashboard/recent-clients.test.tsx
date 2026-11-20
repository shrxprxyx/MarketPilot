import { render, screen } from "@testing-library/react";
import { RecentClients } from "@/components/dashboard/recent-clients";

type Result = { data?: unknown; isLoading?: boolean; isError?: boolean };
let clients: Result = {};
vi.mock("@/lib/queries/clients", () => ({ useClients: () => clients }));

const client = (i: number, over: Record<string, unknown> = {}) => ({
  id: `c${i}`,
  name: `Client ${i}`,
  website_url: null,
  industry: null,
  goals: null,
  status: "active",
  ...over,
});

beforeEach(() => {
  clients = { data: { items: [], next_cursor: null } };
});

describe("RecentClients", () => {
  it("shows at most five clients, each linking to its page", () => {
    clients = { data: { items: Array.from({ length: 7 }, (_, i) => client(i + 1)), next_cursor: null } };
    render(<RecentClients />);
    expect(screen.getAllByRole("link", { name: /Client \d/ })).toHaveLength(5);
    expect(screen.getByRole("link", { name: /Client 1/ })).toHaveAttribute("href", "/clients/c1");
    expect(screen.queryByText("Client 6")).not.toBeInTheDocument();
  });

  it("shows the website host (or No website), the industry once, and a status pill", () => {
    clients = {
      data: {
        items: [
          client(1, { website_url: "https://www.bloom.example/shop", industry: "Food" }),
          client(2, { industry: "Retail", status: "archived" }),
        ],
        next_cursor: null,
      },
    };
    render(<RecentClients />);
    expect(screen.getByText("www.bloom.example")).toBeInTheDocument();
    expect(screen.getByText("No website")).toBeInTheDocument();
    expect(screen.getByText("Retail")).toBeInTheDocument(); // only in the Industry column
    expect(screen.getByText("active")).toBeInTheDocument();
    expect(screen.getByText("archived")).toBeInTheDocument();
  });

  it("shows an empty state with a call to action when there are no clients", () => {
    render(<RecentClients />);
    expect(screen.getByText("No clients yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Create your first client/ })).toHaveAttribute(
      "href",
      "/clients",
    );
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("truncates a very long client name", () => {
    clients = { data: { items: [client(1, { name: "N".repeat(150) })], next_cursor: null } };
    render(<RecentClients />);
    expect(screen.getByText("N".repeat(150))).toHaveClass("truncate");
  });

  it("shows skeleton rows while loading", () => {
    clients = { isLoading: true };
    render(<RecentClients />);
    expect(screen.getByTestId("recent-skeleton")).toBeInTheDocument();
  });

  it("shows an error message when clients can't be loaded", () => {
    clients = { isError: true };
    render(<RecentClients />);
    expect(screen.getByText("Couldn't load clients")).toBeInTheDocument();
  });
});
