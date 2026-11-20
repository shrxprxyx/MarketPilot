"use client";

import { Button } from "@/components/ui/button";
import { signOut } from "@/lib/api/client";
import { useSession } from "@/lib/auth/session-store";

// Placeholder home; replaced by the app shell and client list in the next stage.
export default function HomePage() {
  const me = useSession((s) => s.me);
  return (
    <div className="flex flex-col items-start gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">You&apos;re signed in</h1>
      <p className="text-muted-foreground">Role: {me?.role}</p>
      {/* SessionGate sends the user to /login once the session is cleared. */}
      <Button variant="secondary" onClick={() => void signOut()}>
        Sign out
      </Button>
    </div>
  );
}
