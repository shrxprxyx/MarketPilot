"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { refreshSession } from "@/lib/api/client";
import { useSession } from "@/lib/auth/session-store";

/** Restores the session from the refresh cookie and keeps signed-out users out. */
export function SessionGate({ children }: { children: React.ReactNode }) {
  const status = useSession((s) => s.status);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "unknown") void refreshSession();
  }, [status]);

  useEffect(() => {
    if (status === "anonymous") {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [status, pathname, router]);

  if (status !== "authenticated") {
    return (
      <div
        data-testid="session-skeleton"
        className="flex flex-1 flex-col gap-4 p-8"
      >
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-32 w-full max-w-2xl" />
        <Skeleton className="h-32 w-full max-w-2xl" />
      </div>
    );
  }

  return <>{children}</>;
}
