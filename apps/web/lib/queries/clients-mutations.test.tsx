import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useArchiveClient, useClient, useCreateClient, useUpdateClient } from "@/lib/queries/clients";

// Plain delegate rather than vi.fn(): see lib/queries/tenants.test.tsx.
const calls: { path: string; init?: RequestInit }[] = [];
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    return { id: "new1", name: "Acme" };
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  calls.length = 0;
});

describe("client hooks", () => {
  it("fetches one client by id", async () => {
    renderHook(() => useClient("c1"), { wrapper });
    await waitFor(() => expect(calls.map((c) => c.path)).toEqual(["/clients/c1"]));
  });

  it("creates a client with a POST and the JSON body", async () => {
    const { result } = renderHook(() => useCreateClient(), { wrapper });
    let out: unknown;
    await act(async () => {
      out = await result.current.mutateAsync({ name: "Acme", industry: "Pets" });
    });
    expect(calls[0].path).toBe("/clients");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(calls[0].init?.body as string)).toEqual({ name: "Acme", industry: "Pets" });
    expect(out).toEqual({ id: "new1", name: "Acme" });
  });

  it("updates a client with a PATCH and the JSON patch", async () => {
    const { result } = renderHook(() => useUpdateClient("c1"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ industry: null, status: "active" });
    });
    expect(calls[0].path).toBe("/clients/c1");
    expect(calls[0].init?.method).toBe("PATCH");
    expect(JSON.parse(calls[0].init?.body as string)).toEqual({ industry: null, status: "active" });
  });

  it("archives a client with a DELETE", async () => {
    const { result } = renderHook(() => useArchiveClient("c1"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync();
    });
    expect(calls[0].path).toBe("/clients/c1");
    expect(calls[0].init?.method).toBe("DELETE");
  });
});
