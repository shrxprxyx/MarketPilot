import { NextResponse, type NextRequest } from "next/server";

export const REFRESH_COOKIE = "mp_refresh";
// The browser client sends this on /api/auth/refresh. A cross-site form post cannot add a
// custom header, so the cookie alone is not enough to rotate a session (SRS section 11, CSRF).
export const CSRF_HEADER = "x-mp-csrf";
const SEVEN_DAYS = 60 * 60 * 24 * 7; // matches the API's refresh token lifetime

const apiUrl = () => process.env.API_URL ?? "http://localhost:8000/api/v1";

function problem(status: number, title: string, detail: string) {
  return NextResponse.json({ status, title, detail }, { status });
}

/** The browser's address as the platform in front of Next.js saw it. The API's login lockout and
 * audit log would otherwise record this server's address for every user. */
export function clientHeaders(req: NextRequest): HeadersInit {
  const forwarded = req.headers.get("x-forwarded-for");
  return forwarded ? { "x-forwarded-for": forwarded } : {};
}

function setRefreshCookie(res: NextResponse, token: string) {
  res.cookies.set(REFRESH_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SEVEN_DAYS,
  });
}

function clearRefreshCookie(res: NextResponse) {
  res.cookies.set(REFRESH_COOKIE, "", { path: "/", maxAge: 0 });
}

async function callApi(apiPath: string, body: object, headers?: HeadersInit) {
  try {
    return await fetch(`${apiUrl()}${apiPath}`, {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: JSON.stringify(body),
    });
  } catch {
    return null;
  }
}

const unreachable = () =>
  problem(502, "Bad Gateway", "Can't reach the server. Please try again.");

/** Calls a FastAPI token endpoint; keeps the refresh token in a cookie, never in the body. */
export async function forwardTokenCall(
  apiPath: string,
  body: object,
  headers?: HeadersInit,
): Promise<NextResponse> {
  const res = await callApi(apiPath, body, headers);
  if (!res) return unreachable();
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    return NextResponse.json(
      data ?? { status: res.status, title: "Error", detail: "Something went wrong. Please try again." },
      { status: res.status },
    );
  }
  const out = NextResponse.json({ access_token: data.access_token });
  setRefreshCookie(out, data.refresh_token);
  return out;
}

export async function refreshFromCookie(req: NextRequest): Promise<NextResponse> {
  const token = req.cookies.get(REFRESH_COOKIE)?.value;
  if (req.headers.get(CSRF_HEADER) !== "1") {
    return problem(403, "Forbidden", "Missing request header.");
  }
  if (!token) return problem(401, "Unauthorized", "Not signed in.");
  const headers = clientHeaders(req);
  let res = await forwardTokenCall("/auth/refresh", { refresh_token: token }, headers);
  // The API closes idle keep-alive sockets after ~5s, so a pooled connection can be reset just
  // as it is reused. Without a retry that surfaces as 502 and signs the user out. Retrying is
  // safe: a refresh the API already processed is absorbed by its reuse grace window.
  if (res.status === 502) {
    res = await forwardTokenCall("/auth/refresh", { refresh_token: token }, headers);
  }
  if (res.status === 401) clearRefreshCookie(res);
  return res;
}

export async function logoutFromCookie(req: NextRequest): Promise<NextResponse> {
  const token = req.cookies.get(REFRESH_COOKIE)?.value;
  if (token) await callApi("/auth/logout", { refresh_token: token }, clientHeaders(req));
  const out = new NextResponse(null, { status: 204 });
  clearRefreshCookie(out);
  return out;
}
