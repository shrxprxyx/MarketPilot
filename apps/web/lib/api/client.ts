import { useSession, type Me } from "@/lib/auth/session-store";
import { ApiError, networkError, parseProblem } from "@/lib/api/problem";

async function send(path: string, init: RequestInit = {}, token?: string | null) {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  if (token) headers.set("authorization", `Bearer ${token}`);
  try {
    return await fetch(`/api${path}`, { ...init, headers });
  } catch {
    throw networkError();
  }
}

async function readJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw await parseProblem(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

let inflight: Promise<boolean> | null = null;

/** Exchanges the refresh cookie for a new access token and loads /me. */
export function refreshSession(): Promise<boolean> {
  inflight ??= doRefresh().finally(() => {
    inflight = null;
  });
  return inflight;
}

async function doRefresh(): Promise<boolean> {
  try {
    const refreshed = await send("/auth/refresh", { method: "POST" });
    if (!refreshed.ok) {
      useSession.getState().clear();
      return false;
    }
    const { access_token } = (await refreshed.json()) as { access_token: string };
    const me = await readJson<Me>(await send("/me", {}, access_token));
    useSession.getState().setSession(access_token, me);
    return true;
  } catch {
    useSession.getState().clear();
    return false;
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let res = await send(path, init, useSession.getState().accessToken);
  if (res.status === 401) {
    if (!(await refreshSession())) {
      throw await parseProblem(res);
    }
    res = await send(path, init, useSession.getState().accessToken);
  }
  return readJson<T>(res);
}

export async function signIn(
  path: "login" | "register" | "accept-invite",
  body: object,
): Promise<void> {
  const res = await send(`/auth/${path}`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  const { access_token } = await readJson<{ access_token: string }>(res);
  const me = await readJson<Me>(await send("/me", {}, access_token));
  useSession.getState().setSession(access_token, me);
}

/** Moves the session to another agency the user belongs to (new token pair, cookie rotated). */
export async function switchTenant(tenantId: string): Promise<void> {
  const { access_token } = await apiFetch<{ access_token: string }>(
    "/auth/switch-tenant",
    { method: "POST", body: JSON.stringify({ tenant_id: tenantId }) },
  );
  const me = await readJson<Me>(await send("/me", {}, access_token));
  useSession.getState().setSession(access_token, me);
}

export async function signOut(): Promise<void> {
  try {
    await send("/auth/logout", { method: "POST" });
  } finally {
    useSession.getState().clear();
  }
}

export { ApiError };
