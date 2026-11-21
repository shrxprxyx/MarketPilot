import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import {
  useAiRoutes,
  useDeleteConnection,
  useSaveRoutes,
  useTestConnection,
} from "@/lib/queries/ai";

// Plain delegate rather than vi.fn(): see lib/queries/tenants.test.tsx.
const calls: { path: string; init?: RequestInit }[] = [];
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    return path.endsWith("/test") ? { ok: true, models: ["m1"] } : [];
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  calls.length = 0;
});

describe("AI routing and connection hooks", () => {
  it("requests routes only when enabled", async () => {
    renderHook(() => useAiRoutes(false), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(calls).toEqual([]);
    renderHook(() => useAiRoutes(true), { wrapper });
    await waitFor(() => expect(calls.map((c) => c.path)).toEqual(["/ai/routes"]));
  });

  it("tests a connection with POST and returns the model list", async () => {
    const { result } = renderHook(() => useTestConnection(), { wrapper });
    let out: unknown;
    await act(async () => {
      out = await result.current.mutateAsync("abc");
    });
    expect(calls[0].path).toBe("/ai/connections/abc/test");
    expect(calls[0].init?.method).toBe("POST");
    expect(out).toEqual({ ok: true, models: ["m1"] });
  });

  it("deletes a connection with DELETE", async () => {
    const { result } = renderHook(() => useDeleteConnection(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync("abc");
    });
    expect(calls[0].path).toBe("/ai/connections/abc");
    expect(calls[0].init?.method).toBe("DELETE");
  });

  it("saves routes with PUT and the array as JSON", async () => {
    const body = [
      { task_type: "strategy", connection_id: "c", model: "m", temperature: 0.7, max_tokens: 100 },
    ] as const;
    const { result } = renderHook(() => useSaveRoutes(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync([...body]);
    });
    expect(calls[0].path).toBe("/ai/routes");
    expect(calls[0].init?.method).toBe("PUT");
    expect(JSON.parse(calls[0].init?.body as string)).toEqual(body);
  });
});
