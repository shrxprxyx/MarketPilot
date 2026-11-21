"use client";

import { useCallback, useState } from "react";
import { ConnectionsSection } from "@/components/ai/connections-section";
import { RoutingSection } from "@/components/ai/routing-section";
import { useSession } from "@/lib/auth/session-store";

export function AiSettingsPage() {
  const role = useSession((s) => s.me?.role);
  // Model names come only from a connection's Test call; Routing uses them as suggestions.
  const [testedModels, setTestedModels] = useState<Record<string, string[]>>({});
  const onTested = useCallback(
    (connectionId: string, models: string[]) =>
      setTestedModels((prev) => ({ ...prev, [connectionId]: models })),
    [],
  );

  if (!role) return null;

  return (
    <div className="flex max-w-5xl flex-col gap-12">
      <header>
        <p className="mb-4 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          AI
        </p>
        <h1 className="font-heading text-4xl font-semibold leading-tight tracking-tight">
          AI models
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
          Connect your own AI models and choose which one handles each task.
        </p>
      </header>
      {role === "member" ? (
        <p className="border-y py-10 text-sm text-muted-foreground">
          Only admins and managers can manage AI models. Ask an admin if you need a change.
        </p>
      ) : (
        <>
          <ConnectionsSection testedModels={testedModels} onTested={onTested} />
          <RoutingSection testedModels={testedModels} />
        </>
      )}
    </div>
  );
}
