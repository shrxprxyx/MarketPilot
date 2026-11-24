import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useSession } from "@/lib/auth/session-store";
import { useRenameTenant, useSaveBranding, useTenantDetail } from "@/lib/queries/tenant";

const calls: { path: string; init?: RequestInit }[] = [];
let reply: unknown = {};
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    return reply;
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

const detail = (name: string) => ({
  id: "t",
  name,
  slug: "s",
  plan: "free",
  branding: { logo_url: null, primary_color: null, report_footer: null },
});

beforeEach(() => {
  calls.length = 0;
  reply = detail("Acme Agency");
  useSession.getState().setSession("tok", {
    user_id: "u",
    tenant_id: "t",
    role: "admin",
    email: "a@b.co",
    tenant_name: "Acme Agency",
  });
});

describe("tenant hooks", () => {
  it("loads the agency, and sends nothing when disabled", async () => {
    const off = renderHook(() => useTenantDetail(false), { wrapper });
    expect(off.result.current.fetchStatus).toBe("idle");
    expect(calls).toHaveLength(0);
    const on = renderHook(() => useTenantDetail(true), { wrapper });
    await waitFor(() => expect(on.result.current.isSuccess).toBe(true));
    expect(calls[0].path).toBe("/tenant");
  });

  it("renames with PATCH and updates the name the shell shows", async () => {
    reply = detail("Acme Studio");
    const { result } = renderHook(() => useRenameTenant(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync("Acme Studio");
    });
    expect(calls[0].path).toBe("/tenant");
    expect(calls[0].init?.method).toBe("PATCH");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ name: "Acme Studio" });
    expect(useSession.getState().me?.tenant_name).toBe("Acme Studio");
    expect(useSession.getState().accessToken).toBe("tok"); // the session itself is untouched
  });

  it("saves branding with PUT", async () => {
    const branding = { logo_url: "https://x.co/l.png", primary_color: "#112233", report_footer: null };
    const { result } = renderHook(() => useSaveBranding(), { wrapper });
    await act(async () => {
      await result.current.mutateAsync(branding);
    });
    expect(calls[0].path).toBe("/tenant/branding");
    expect(calls[0].init?.method).toBe("PUT");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual(branding);
    expect(useSession.getState().me?.tenant_name).toBe("Acme Agency");
  });
});
