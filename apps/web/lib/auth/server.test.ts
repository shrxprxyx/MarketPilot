// @vitest-environment node
import { NextRequest } from "next/server";
import { POST as login } from "@/app/api/auth/login/route";
import { POST as refresh } from "@/app/api/auth/refresh/route";
import { POST as logout } from "@/app/api/auth/logout/route";
import { REFRESH_COOKIE } from "@/lib/auth/server";

function req(path: string, body?: unknown, cookie?: string) {
  return new NextRequest(`http://localhost:3000${path}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-mp-csrf": "1",
      ...(cookie ? { cookie: `${REFRESH_COOKIE}=${cookie}` } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function apiReturns(status: number, body?: unknown) {
  const fn = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () =>
    status === 204
      ? new Response(null, { status })
      : new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => vi.unstubAllGlobals());

describe("login handler", () => {
  it("sets an HttpOnly refresh cookie and returns only the access token", async () => {
    apiReturns(200, { access_token: "A", refresh_token: "R", token_type: "bearer" });
    const res = await login(req("/api/auth/login", { email: "a@b.co", password: "pw" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ access_token: "A" });
    const cookie = res.cookies.get(REFRESH_COOKIE);
    expect(cookie?.value).toBe("R");
    expect(res.headers.get("set-cookie")).toMatch(/HttpOnly/i);
    expect(res.headers.get("set-cookie")).toMatch(/SameSite=lax/i);
  });

  it("passes an API 401 problem through and sets no cookie", async () => {
    apiReturns(401, { status: 401, title: "Unauthorized", detail: "Invalid credentials." });
    const res = await login(req("/api/auth/login", { email: "a@b.co", password: "bad" }));
    expect(res.status).toBe(401);
    expect(await res.json()).toMatchObject({ detail: "Invalid credentials." });
    expect(res.headers.get("set-cookie")).toBeNull();
  });

  it("returns a 502 problem when the API is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    const res = await login(req("/api/auth/login", { email: "a@b.co", password: "pw" }));
    expect(res.status).toBe(502);
    expect(await res.json()).toMatchObject({ detail: "Can't reach the server. Please try again." });
  });
});

describe("refresh handler", () => {
  it("returns 401 when there is no cookie, without calling the API", async () => {
    const fetchMock = apiReturns(200, {});
    const res = await refresh(req("/api/auth/refresh"));
    expect(res.status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rotates the cookie on success", async () => {
    const fetchMock = apiReturns(200, { access_token: "A2", refresh_token: "R2" });
    const res = await refresh(req("/api/auth/refresh", undefined, "R1"));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ access_token: "A2" });
    expect(res.cookies.get(REFRESH_COOKIE)?.value).toBe("R2");
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({ refresh_token: "R1" });
  });

  it("clears the cookie and returns 401 when the API rejects the token", async () => {
    apiReturns(401, { status: 401, title: "Unauthorized", detail: "Invalid or expired refresh token." });
    const res = await refresh(req("/api/auth/refresh", undefined, "stale"));
    expect(res.status).toBe(401);
    expect(res.headers.get("set-cookie")).toMatch(new RegExp(`${REFRESH_COOKIE}=;|Max-Age=0|Expires=Thu, 01 Jan 1970`, "i"));
  });
});

describe("refresh handler: CSRF header and client address", () => {
  it("refuses a refresh without the custom header, without calling the API", async () => {
    const fetchMock = apiReturns(200, { access_token: "A", refresh_token: "R" });
    const bare = new NextRequest("http://localhost:3000/api/auth/refresh", {
      method: "POST",
      headers: { cookie: `${REFRESH_COOKIE}=R1` },
    });
    const res = await refresh(bare);
    expect(res.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("passes the browser's address on to the API", async () => {
    const fetchMock = apiReturns(200, { access_token: "A", refresh_token: "R" });
    const r = new NextRequest("http://localhost:3000/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json", "x-forwarded-for": "203.0.113.9" },
      body: JSON.stringify({ email: "a@b.co", password: "pw" }),
    });
    await login(r);
    const [, init] = fetchMock.mock.calls[0];
    expect(new Headers(init?.headers).get("x-forwarded-for")).toBe("203.0.113.9");
  });
});

describe("refresh handler: unreachable API", () => {
  it("retries once when the first call fails to connect, and keeps the session", async () => {
    const fetchMock = vi
      .fn<(url: string, init?: RequestInit) => Promise<Response>>()
      .mockRejectedValueOnce(new TypeError("fetch failed"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: "A2", refresh_token: "R2" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const res = await refresh(req("/api/auth/refresh", undefined, "R1"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(res.status).toBe(200);
    expect(res.cookies.get(REFRESH_COOKIE)?.value).toBe("R2");
  });

  it("returns 502 without clearing the cookie when the API stays unreachable", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("fetch failed"));
    vi.stubGlobal("fetch", fetchMock);
    const res = await refresh(req("/api/auth/refresh", undefined, "R1"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(res.status).toBe(502);
    expect(res.headers.get("set-cookie")).toBeNull();
  });
});

describe("logout handler", () => {
  it("returns 204 and clears the cookie even when no cookie was sent", async () => {
    const fetchMock = apiReturns(204);
    const res = await logout(req("/api/auth/logout"));
    expect(res.status).toBe(204);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("revokes the token at the API and clears the cookie", async () => {
    const fetchMock = apiReturns(204);
    const res = await logout(req("/api/auth/logout", undefined, "R1"));
    expect(res.status).toBe(204);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(res.headers.get("set-cookie")).toMatch(/Max-Age=0|Expires=Thu, 01 Jan 1970/i);
  });
});
