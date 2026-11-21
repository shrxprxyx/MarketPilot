import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useAiUsage, useAiUsageBy } from "@/lib/queries/ai";

// Plain delegate rather than vi.fn(): see lib/queries/tenants.test.tsx.
const calls: string[] = [];
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string) => {
    calls.push(path);
    return [];
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  calls.length = 0;
});

describe("useAiUsageBy", () => {
  it("requests the given grouping and range", async () => {
    renderHook(() => useAiUsageBy("task", 7, true), { wrapper });
    await waitFor(() => expect(calls).toEqual(["/ai/usage?group_by=task&days=7"]));
  });

  it("sends nothing when disabled", async () => {
    renderHook(() => useAiUsageBy("task", 7, false), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(calls).toEqual([]);
  });

  it("leaves the dashboard's fixed 30-day daily hook unchanged", async () => {
    renderHook(() => useAiUsage(true), { wrapper });
    await waitFor(() => expect(calls).toEqual(["/ai/usage?group_by=day&days=30"]));
  });
});
