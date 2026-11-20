import type { NextRequest } from "next/server";
import { logoutFromCookie } from "@/lib/auth/server";

export async function POST(req: NextRequest) {
  return logoutFromCookie(req);
}
