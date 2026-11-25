import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { ApiError } from "@/lib/api/problem";
import { useBrandProfile, useSaveBrandProfile } from "@/lib/queries/brand-profile";

// Plain delegate rather than vi.fn(): see lib/queries/tenants.test.tsx.
const calls: { path: string; init?: RequestInit }[] = [];
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    if (failWith) throw failWith;
    return {};
  },
}));
let failWith: Error | null = null;

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  calls.length = 0;
  failWith = null;
});

describe("brand profile hooks", () => {
  it("fetches a client's brand profile", async () => {
    renderHook(() => useBrandProfile("c1"), { wrapper });
    await waitFor(() => expect(calls.map((c) => c.path)).toEqual(["/clients/c1/brand-profile"]));
  });

  it("treats 404 (nothing saved yet) as an empty result, not an error", async () => {
    failWith = new ApiError(404, "Not Found", "none");
    const { result } = renderHook(() => useBrandProfile("c1"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("still surfaces other errors", async () => {
    failWith = new ApiError(500, "Error", "boom");
    const { result } = renderHook(() => useBrandProfile("c1"), { wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("saves with a PUT and the full profile as JSON", async () => {
    const input = {
      voice: "Warm",
      tone: null,
      audience: null,
      keywords: ["a"],
      do_rules: null,
      dont_rules: null,
      sample_text: null,
    };
    const { result } = renderHook(() => useSaveBrandProfile("c1"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync(input);
    });
    expect(calls[0].path).toBe("/clients/c1/brand-profile");
    expect(calls[0].init?.method).toBe("PUT");
    expect(JSON.parse(calls[0].init?.body as string)).toEqual(input);
  });
});
