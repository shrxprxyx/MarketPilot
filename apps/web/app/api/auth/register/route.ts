import type { NextRequest } from "next/server";
import { clientHeaders, forwardTokenCall } from "@/lib/auth/server";

export async function POST(req: NextRequest) {
  return forwardTokenCall("/auth/register", await req.json().catch(() => ({})), clientHeaders(req));
}
