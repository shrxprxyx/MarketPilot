import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useBudget } from "@/lib/queries/budget";
import { useGenerateStrategy, useStrategies } from "@/lib/queries/strategies";

const calls: { path: string; init?: RequestInit }[] = [];
let postFails = false;
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    if (init?.method === "POST" && postFails) throw new Error("connection lost");
    return init?.method === "POST" ? { id: "s1" } : { items: [], next_cursor: null };
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  calls.length = 0;
  postFails = false;
});

const sentKeys = () =>
  calls
    .filter((c) => c.init?.method === "POST")
    .map((c) => new Headers(c.init?.headers).get("Idempotency-Key"));

describe("strategy hooks", () => {
  it("lists a client's strategies", async () => {
    const { result } = renderHook(() => useStrategies("c1"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(calls[0].path).toBe("/clients/c1/strategies?limit=100");
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

  it("reuses the key after a failure, so a retry cannot be billed twice", async () => {
    const { result } = renderHook(() => useGenerateStrategy("c1"), { wrapper });
    postFails = true;
    await act(async () => {
      await result.current.mutateAsync({ month: "2026-12" }).catch(() => {});
    });
    postFails = false;
    await act(async () => {
      await result.current.mutateAsync({ month: "2026-12" });
    });
    const [first, retry] = sentKeys();
    expect(first).toMatch(/^[A-Za-z0-9._:-]{8,100}$/); // the format the API accepts
    expect(retry).toBe(first);
  });

  it("uses a new key after a success, and a separate one for each month", async () => {
    const { result } = renderHook(() => useGenerateStrategy("c1"), { wrapper });
    postFails = true;
    await act(async () => {
      await result.current.mutateAsync({ month: "2026-11" }).catch(() => {});
    });
    postFails = false;
    for (const month of ["2026-12", "2026-12"]) {
      await act(async () => {
        await result.current.mutateAsync({ month });
      });
    }
    expect(new Set(sentKeys()).size).toBe(3);
  });

  it("still sends a valid key where crypto.randomUUID is unavailable", async () => {
    vi.stubGlobal("crypto", {}); // plain http on a LAN address has no randomUUID
    try {
      const { result } = renderHook(() => useGenerateStrategy("c1"), { wrapper });
      await act(async () => {
        await result.current.mutateAsync({ month: "2026-12" });
      });
      expect(sentKeys()[0]).toMatch(/^[A-Za-z0-9._:-]{8,100}$/);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
