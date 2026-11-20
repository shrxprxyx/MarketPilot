"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { signIn } from "@/lib/api/client";
import { ApiError, GENERIC_DETAIL } from "@/lib/api/problem";
import { safeNext } from "@/lib/auth/safe-next";

/** Shared submit flow for the three auth forms: call the API, then go to ?next=. */
export function useAuthSubmit(path: "login" | "register" | "accept-invite") {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const [error, setError] = useState<string | null>(null);

  async function submit(body: object) {
    setError(null);
    try {
      await signIn(path, body);
      router.replace(safeNext(next));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : GENERIC_DETAIL);
    }
  }

  return { error, submit };
}
