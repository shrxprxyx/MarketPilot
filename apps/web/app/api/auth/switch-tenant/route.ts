import type { NextRequest } from "next/server";
import { clientHeaders, forwardTokenCall } from "@/lib/auth/server";

export async function POST(req: NextRequest) {
  const auth = req.headers.get("authorization");
  return forwardTokenCall(
    "/auth/switch-tenant",
    await req.json().catch(() => ({})),
    { ...clientHeaders(req), ...(auth ? { authorization: auth } : {}) },
  );
}
