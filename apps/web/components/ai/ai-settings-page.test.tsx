import { render, screen } from "@testing-library/react";
import { AiSettingsPage } from "@/components/ai/ai-settings-page";
import { useSession, type Role } from "@/lib/auth/session-store";

const enabledFlags: boolean[] = [];
let lastConnections: { testedModels: Record<string, string[]>; onTested: (id: string, m: string[]) => void };
let lastRouting: { testedModels: Record<string, string[]> };

vi.mock("@/components/ai/connections-section", () => ({
  ConnectionsSection: (p: typeof lastConnections) => {
    lastConnections = p;
    enabledFlags.push(true);
    return <div>connections-section</div>;
  },
}));
vi.mock("@/components/ai/routing-section", () => ({
  RoutingSection: (p: typeof lastRouting) => {
    lastRouting = p;
    enabledFlags.push(true);
    return <div>routing-section</div>;
  },
}));

function as(role: Role) {
  useSession.getState().setSession("t", {
    user_id: "u",
    tenant_id: "t",
    role,
    email: "a@b.co",
    tenant_name: "Acme",
  });
}

beforeEach(() => {
  enabledFlags.length = 0;
  useSession.getState().clear();
});

describe("AiSettingsPage", () => {
  it("shows a managers-only message to members and renders no data sections", () => {
    as("member");
    render(<AiSettingsPage />);
    expect(screen.getByText(/only admins and managers/i)).toBeInTheDocument();
    expect(screen.queryByText("connections-section")).not.toBeInTheDocument();
    expect(enabledFlags).toHaveLength(0);
  });

  it.each(["admin", "manager"] as Role[])("renders both sections for %s", (role) => {
    as(role);
    render(<AiSettingsPage />);
    expect(screen.getByRole("heading", { name: "AI models" })).toBeInTheDocument();
    expect(screen.getByText("connections-section")).toBeInTheDocument();
    expect(screen.getByText("routing-section")).toBeInTheDocument();
  });

  it("shares tested model names from Connections with Routing", async () => {
    as("admin");
    const { rerender } = render(<AiSettingsPage />);
    expect(lastRouting.testedModels).toEqual({});
    const { act } = await import("@testing-library/react");
    act(() => lastConnections.onTested("c1", ["m1"]));
    rerender(<AiSettingsPage />);
    expect(lastRouting.testedModels).toEqual({ c1: ["m1"] });
  });
});
