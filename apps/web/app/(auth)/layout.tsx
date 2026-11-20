import { Suspense } from "react";
import { RedirectIfAuthed } from "@/components/auth/redirect-if-authed";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-svh flex-1 flex-col items-center justify-center gap-6 bg-[radial-gradient(60%_45%_at_50%_0%,oklch(0.62_0.2_277/0.16),transparent)] p-6">
      <p className="text-lg font-semibold tracking-tight">MarketPilot</p>
      {/* useSearchParams in the forms needs a Suspense boundary (cacheComponents). */}
      <Suspense>
        <RedirectIfAuthed />
        {children}
      </Suspense>
    </main>
  );
}
