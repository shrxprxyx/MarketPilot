import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { useTenants } from "@/lib/queries/tenants";

// A plain delegate rather than vi.fn(): Vitest reports a rejected promise returned
// from a spy as an unhandled error, even when the caller handles it.
const calls: string[] = [];
let impl: (path: string) => Promise<unknown> = async () => [];
vi.mock("@/lib/api/client", () => ({
  apiFetch: (path: string) => {
    calls.push(path);
    return impl(path);
  },
}));

function makeWrapper() {
  // One client per test: a client created inside the wrapper would reset on every re-render.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  calls.length = 0;
});

describe("useTenants", () => {
  it("loads the caller's agencies from /me/tenants", async () => {
    const tenants = [
      { id: "t1", name: "Acme", role: "admin" },
      { id: "t2", name: "Globex", role: "manager" },
    ];
    impl = async () => tenants;
    const { result } = renderHook(() => useTenants(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(tenants);
    expect(calls).toEqual(["/me/tenants"]);
  });

  it("exposes an error when the request fails", async () => {
    impl = async () => {
      throw new Error("boom");
    };
    const { result } = renderHook(() => useTenants(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("boom");
  });
});
