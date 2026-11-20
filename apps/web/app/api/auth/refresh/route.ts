import type { NextRequest } from "next/server";
import { refreshFromCookie } from "@/lib/auth/server";

export async function POST(req: NextRequest) {
  return refreshFromCookie(req);
}
