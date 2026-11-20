import { ApiError } from "@/lib/api/problem";
import { apiFetch, refreshSession, signIn, signOut, switchTenant } from "@/lib/api/client";
import { useSession } from "@/lib/auth/session-store";

const me = { user_id: "u1", tenant_id: "t1", role: "admin", email: "a@b.co", tenant_name: "Acme" };

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

type Handler = (req: Request) => Response | Promise<Response>;

/** Routes fetch calls by "METHOD /path" and records every call. */
function mockFetch(routes: Record<string, Handler>) {
  const calls: { key: string; auth: string | null }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = new Request(new URL(String(input), "http://localhost"), init);
    const key = `${req.method} ${new URL(req.url).pathname}`;
    calls.push({ key, auth: req.headers.get("authorization") });
    const handler = routes[key];
    if (!handler) throw new Error(`unmocked ${key}`);
    return handler(req);
  });
  vi.stubGlobal("fetch", fn);
  return { calls, count: (key: string) => calls.filter((c) => c.key === key).length };
}

beforeEach(() => {
  useSession.getState().clear();
  useSession.setState({ status: "unknown" });
});
afterEach(() => vi.unstubAllGlobals());

describe("apiFetch", () => {
  it("sends the access token as a Bearer header and returns parsed JSON", async () => {
    useSession.getState().setSession("tok", me as never);
    const m = mockFetch({ "GET /api/clients": () => json({ items: [] }) });
    await expect(apiFetch("/clients")).resolves.toEqual({ items: [] });
    expect(m.calls[0].auth).toBe("Bearer tok");
  });

  it("returns undefined for a 204 response", async () => {
    useSession.getState().setSession("tok", me as never);
    mockFetch({ "DELETE /api/clients/1": () => new Response(null, { status: 204 }) });
    await expect(apiFetch("/clients/1", { method: "DELETE" })).resolves.toBeUndefined();
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    useSession.getState().setSession("old", me as never);
    const m = mockFetch({
      "GET /api/clients": (req) =>
        req.headers.get("authorization") === "Bearer new"
          ? json({ ok: true })
          : json({ status: 401, title: "Unauthorized", detail: "expired" }, 401),
      "POST /api/auth/refresh": () => json({ access_token: "new" }),
      "GET /api/me": () => json(me),
    });
    await expect(apiFetch("/clients")).resolves.toEqual({ ok: true });
    expect(m.count("POST /api/auth/refresh")).toBe(1);
    expect(m.count("GET /api/clients")).toBe(2);
  });

  it("makes exactly one refresh call when three requests get 401 at once", async () => {
    useSession.getState().setSession("old", me as never);
    const m = mockFetch({
      "GET /api/clients": (req) =>
        req.headers.get("authorization") === "Bearer new"
          ? json({ ok: true })
          : json({ status: 401, title: "Unauthorized", detail: "expired" }, 401),
      "POST /api/auth/refresh": () => json({ access_token: "new" }),
      "GET /api/me": () => json(me),
    });
    const results = await Promise.all([apiFetch("/clients"), apiFetch("/clients"), apiFetch("/clients")]);
    expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(m.count("POST /api/auth/refresh")).toBe(1);
  });

  it("clears the session and throws a 401 ApiError when refresh fails", async () => {
    useSession.getState().setSession("old", me as never);
    mockFetch({
      "GET /api/clients": () => json({ status: 401, title: "Unauthorized", detail: "expired" }, 401),
      "POST /api/auth/refresh": () => json({ status: 401, title: "Unauthorized", detail: "no" }, 401),
    });
    await expect(apiFetch("/clients")).rejects.toMatchObject({ status: 401 });
    expect(useSession.getState().status).toBe("anonymous");
  });

  it("turns a non-JSON error body into a generic ApiError", async () => {
    useSession.getState().setSession("tok", me as never);
    mockFetch({ "GET /api/clients": () => new Response("<html>boom</html>", { status: 500 }) });
    const err = (await apiFetch("/clients").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(500);
    expect(err.detail).toBe("Something went wrong. Please try again.");
  });

  it("turns a network failure into a friendly ApiError", async () => {
    useSession.getState().setSession("tok", me as never);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const err = (await apiFetch("/clients").catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.title).toBe("Network error");
    expect(err.detail).toBe("Can't reach the server. Please try again.");
  });
});

describe("refreshSession", () => {
  it("stores the new token and /me and returns true", async () => {
    mockFetch({
      "POST /api/auth/refresh": () => json({ access_token: "new" }),
      "GET /api/me": () => json(me),
    });
    await expect(refreshSession()).resolves.toBe(true);
    expect(useSession.getState().accessToken).toBe("new");
    expect(useSession.getState().status).toBe("authenticated");
  });

  it("returns false and marks anonymous when the cookie is rejected", async () => {
    mockFetch({ "POST /api/auth/refresh": () => json({ status: 401, title: "Unauthorized", detail: "x" }, 401) });
    await expect(refreshSession()).resolves.toBe(false);
    expect(useSession.getState().status).toBe("anonymous");
  });
});

describe("signIn / signOut", () => {
  it("signIn posts the body, then loads /me into the store", async () => {
    let sent: unknown;
    mockFetch({
      "POST /api/auth/login": async (req) => {
        sent = await req.json();
        return json({ access_token: "tok" });
      },
      "GET /api/me": () => json(me),
    });
    await signIn("login", { email: "a@b.co", password: "pw" });
    expect(sent).toEqual({ email: "a@b.co", password: "pw" });
    expect(useSession.getState().accessToken).toBe("tok");
  });

  it("signIn throws the API problem detail on a wrong password", async () => {
    mockFetch({
      "POST /api/auth/login": () => json({ status: 401, title: "Unauthorized", detail: "Invalid credentials." }, 401),
    });
    await expect(signIn("login", { email: "a@b.co", password: "bad" })).rejects.toMatchObject({
      status: 401,
      detail: "Invalid credentials.",
    });
    expect(useSession.getState().status).not.toBe("authenticated");
  });

  it("signOut posts logout and clears the session", async () => {
    useSession.getState().setSession("tok", me as never);
    const m = mockFetch({ "POST /api/auth/logout": () => new Response(null, { status: 204 }) });
    await signOut();
    expect(m.count("POST /api/auth/logout")).toBe(1);
    expect(useSession.getState().status).toBe("anonymous");
  });
});

describe("switchTenant", () => {
  it("posts the tenant id with the Bearer token, then stores the new token and /me", async () => {
    useSession.getState().setSession("old", me as never);
    let sent: unknown;
    const newMe = { ...me, tenant_id: "t2", tenant_name: "Globex", role: "manager" };
    const m = mockFetch({
      "POST /api/auth/switch-tenant": async (req) => {
        sent = await req.json();
        return json({ access_token: "tok2" });
      },
      "GET /api/me": () => json(newMe),
    });
    await switchTenant("t2");
    expect(sent).toEqual({ tenant_id: "t2" });
    expect(m.calls[0].auth).toBe("Bearer old");
    expect(useSession.getState().accessToken).toBe("tok2");
    expect(useSession.getState().me).toEqual(newMe);
  });

  it("throws the API error and keeps the old session when the switch is refused", async () => {
    useSession.getState().setSession("old", me as never);
    mockFetch({
      "POST /api/auth/switch-tenant": () =>
        json({ status: 403, title: "Forbidden", detail: "Not a member of that tenant." }, 403),
    });
    await expect(switchTenant("t9")).rejects.toMatchObject({ status: 403 });
    expect(useSession.getState().accessToken).toBe("old");
    expect(useSession.getState().me).toEqual(me);
  });
});
