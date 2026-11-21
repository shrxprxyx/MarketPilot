import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useBudget, useEstimate, useSaveBudget } from "@/lib/queries/budget";

const calls: { path: string; init?: RequestInit }[] = [];
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    return { ok: true };
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  calls.length = 0;
});

describe("budget hooks", () => {
  it("loads the budget, and sends nothing when disabled", async () => {
    const off = renderHook(() => useBudget(false), { wrapper });
    expect(off.result.current.fetchStatus).toBe("idle");
    expect(calls).toHaveLength(0);
    const on = renderHook(() => useBudget(true), { wrapper });
    await waitFor(() => expect(on.result.current.isSuccess).toBe(true));
    expect(calls[0].path).toBe("/ai/budget");
  });

  it("saves with PUT and refetches the budget", async () => {
    const { result } = renderHook(() => ({ b: useBudget(true), save: useSaveBudget() }), {
      wrapper,
    });
    await waitFor(() => expect(result.current.b.isSuccess).toBe(true));
    await act(async () => {
      await result.current.save.mutateAsync({ monthly_budget_usd: 50, hard_stop: true });
    });
    const put = calls.find((c) => c.init?.method === "PUT");
    expect(put?.path).toBe("/ai/budget");
    expect(JSON.parse(String(put?.init?.body))).toEqual({ monthly_budget_usd: 50, hard_stop: true });
    await waitFor(() => expect(calls.filter((c) => !c.init?.method).length).toBe(2));
  });

  it("fetches an estimate for a client and month, only when enabled", async () => {
    const off = renderHook(() => useEstimate("c1", "2026-12", false), { wrapper });
    expect(off.result.current.fetchStatus).toBe("idle");
    const bad = renderHook(() => useEstimate("c1", "", true), { wrapper });
    expect(bad.result.current.fetchStatus).toBe("idle"); // no month yet: nothing to estimate
    expect(calls).toHaveLength(0);
    const on = renderHook(() => useEstimate("c1", "2026-12", true), { wrapper });
    await waitFor(() => expect(on.result.current.isSuccess).toBe(true));
    expect(calls[0].path).toBe("/ai/usage/estimate?task=strategy&client_id=c1&month=2026-12");
  });
});
