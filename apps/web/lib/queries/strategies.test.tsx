import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useBudget } from "@/lib/queries/budget";
import { useGenerateStrategy, useStrategies } from "@/lib/queries/strategies";

const calls: { path: string; init?: RequestInit }[] = [];
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    return init?.method === "POST" ? { id: "s1" } : [];
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  calls.length = 0;
});

describe("strategy hooks", () => {
  it("lists a client's strategies", async () => {
    const { result } = renderHook(() => useStrategies("c1"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(calls[0].path).toBe("/clients/c1/strategies");
  });

  it("generates with the month as JSON and refetches the list", async () => {
    const { result } = renderHook(
      () => ({ list: useStrategies("c1"), gen: useGenerateStrategy("c1") }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.list.isSuccess).toBe(true));
    await act(async () => {
      await result.current.gen.mutateAsync({ month: "2026-12" });
    });
    const post = calls.find((c) => c.init?.method === "POST");
    expect(post?.path).toBe("/clients/c1/strategies");
    expect(JSON.parse(String(post?.init?.body))).toEqual({ month: "2026-12" });
    await waitFor(() => expect(calls.filter((c) => !c.init?.method).length).toBe(2));
  });

  it("refetches the budget after generating, since spend changed", async () => {
    const { result } = renderHook(
      () => ({ budget: useBudget(true), gen: useGenerateStrategy("c1") }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.budget.isSuccess).toBe(true));
    await act(async () => {
      await result.current.gen.mutateAsync({ month: "2026-12" });
    });
    await waitFor(() => expect(calls.filter((c) => c.path === "/ai/budget").length).toBe(2));
  });
});
