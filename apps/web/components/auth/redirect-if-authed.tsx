"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { refreshSession } from "@/lib/api/client";
import { safeNext } from "@/lib/auth/safe-next";
import { useSession } from "@/lib/auth/session-store";

/** Sends already-signed-in users away from the auth pages. Renders nothing. */
export function RedirectIfAuthed() {
  const status = useSession((s) => s.status);
  const router = useRouter();
  const next = useSearchParams().get("next");

  useEffect(() => {
    if (status === "unknown") void refreshSession();
    if (status === "authenticated") router.replace(safeNext(next));
  }, [status, next, router]);

  return null;
}
