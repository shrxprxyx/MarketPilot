import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useAiConnections, useAiUsage } from "@/lib/queries/ai";
import { useClients } from "@/lib/queries/clients";
import { useMembers } from "@/lib/queries/members";

// Plain delegate rather than vi.fn(): see lib/queries/tenants.test.tsx.
const calls: string[] = [];
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string) => {
    calls.push(path);
    return path.startsWith("/members") ? { items: [], next_cursor: null } : [];
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  calls.length = 0;
});

describe("dashboard query hooks", () => {
  it("requests clients with the given page size", async () => {
    const { result } = renderHook(() => useClients(100), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(calls).toEqual(["/clients?limit=100"]);
  });

  it("requests the three restricted resources when enabled", async () => {
    renderHook(() => [useAiConnections(true), useAiUsage(true), useMembers(true)], { wrapper });
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(calls).toEqual(
      expect.arrayContaining(["/ai/connections", "/ai/usage?group_by=day&days=30", "/members?limit=100"]),
    );
  });

  it("sends no request at all for the restricted resources when disabled", async () => {
    renderHook(() => [useAiConnections(false), useAiUsage(false), useMembers(false)], { wrapper });
    await new Promise((r) => setTimeout(r, 50));
    expect(calls).toEqual([]);
  });
});
