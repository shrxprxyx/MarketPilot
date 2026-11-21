import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useBrandProfile, useSaveBrandProfile } from "@/lib/queries/brand-profile";

// Plain delegate rather than vi.fn(): see lib/queries/tenants.test.tsx.
const calls: { path: string; init?: RequestInit }[] = [];
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    return {};
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  calls.length = 0;
});

describe("brand profile hooks", () => {
  it("fetches a client's brand profile", async () => {
    renderHook(() => useBrandProfile("c1"), { wrapper });
    await waitFor(() => expect(calls.map((c) => c.path)).toEqual(["/clients/c1/brand-profile"]));
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
