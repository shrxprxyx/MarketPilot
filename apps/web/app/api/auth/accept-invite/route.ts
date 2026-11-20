import type { NextRequest } from "next/server";
import { forwardTokenCall } from "@/lib/auth/server";

export async function POST(req: NextRequest) {
  return forwardTokenCall("/auth/accept-invite", await req.json().catch(() => ({})));
}
