"use client";

import { Check, Circle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { Role } from "@/lib/auth/session-store";
import { useAiConnections, useAiUsage } from "@/lib/queries/ai";
import { useClients } from "@/lib/queries/clients";

const DISMISSED_KEY = "marketpilot.getting-started.dismissed";

// Browser storage can be unavailable (private windows, blocked site data): the checklist
// must still render, it just cannot remember being dismissed.
function wasDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === "1";
  } catch {
    return false;
  }
}

type Step = { id: string; title: string; hint: string; done: boolean; href: string; cta: string };

/**
 * First-run checklist (SRS NFR-05): add a client, connect a model, generate a strategy. It
 * disappears once everything is done, or when dismissed. Admins and managers only, since
 * members cannot do any of these steps.
 */
export function GettingStarted({ role }: { role: Role }) {
  const canManage = role === "admin" || role === "manager";
  const clients = useClients(100);
  const connections = useAiConnections(canManage);
  const usage = useAiUsage(canManage);
  const [dismissed, setDismissed] = useState(wasDismissed);

  if (!canManage || dismissed) return null;
  // Wait for real answers, so the list never flashes "nothing done" for an established agency.
  if (clients.isLoading || connections.isLoading || usage.isLoading) return null;
  if (clients.isError || connections.isError || usage.isError) return null;

  const clientItems = clients.data?.items ?? [];
  const steps: Step[] = [
    {
      id: "agency",
      title: "Create your agency",
      hint: "Your workspace is ready.",
      done: true,
      href: "/",
      cta: "",
    },
    {
      id: "client",
      title: "Add your first client",
      hint: "The business you run marketing for, with its brand profile.",
      done: clientItems.length > 0,
      href: "/clients",
      cta: "Add a client",
    },
    {
      id: "model",
      title: "Connect an AI model",
      hint: "Bring your own key for OpenAI or Anthropic, or point to Ollama.",
      done: (connections.data ?? []).length > 0,
      href: "/settings/ai",
      cta: "Connect a model",
    },
    {
      id: "strategy",
      title: "Generate a strategy",
      hint: "Add knowledge documents to a client, then generate its monthly strategy.",
      done: (usage.data ?? []).some((r) => r.calls > 0),
      href: clientItems[0] ? `/clients/${clientItems[0].id}` : "/clients",
      cta: "Open a client",
    },
  ];
  const doneCount = steps.filter((s) => s.done).length;
  if (doneCount === steps.length) return null;

  function dismiss() {
    setDismissed(true);
    try {
      window.localStorage.setItem(DISMISSED_KEY, "1");
    } catch {
      /* not remembered; the checklist simply returns on the next visit */
    }
  }

  const next = steps.find((s) => !s.done);

  return (
    <section aria-labelledby="getting-started-title" className="border-y py-8">
      <div className="mb-6 flex items-baseline justify-between gap-4">
        <div>
          <h2
            id="getting-started-title"
            className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground"
          >
            Getting started
          </h2>
          <p className="mt-2 text-sm text-muted-foreground" aria-live="polite">
            {doneCount} of {steps.length} done
          </p>
        </div>
        <Button variant="ghost" size="sm" className="cursor-pointer" onClick={dismiss}>
          Dismiss
        </Button>
      </div>
      <ol className="flex flex-col gap-5">
        {steps.map((s) => (
          <li key={s.id} className="flex items-start gap-4">
            {s.done ? (
              <Check aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-emerald-500" />
            ) : (
              <Circle aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-muted-foreground" />
            )}
            <div className="min-w-0 flex-1">
              <p className={s.done ? "font-medium text-muted-foreground line-through" : "font-medium"}>
                {s.title}
                <span className="sr-only">{s.done ? " (done)" : " (not done yet)"}</span>
              </p>
              {!s.done && <p className="mt-1 text-sm text-muted-foreground">{s.hint}</p>}
            </div>
            {!s.done && s.id === next?.id && (
              <Link
                href={s.href}
                className="shrink-0 text-sm font-medium underline underline-offset-4"
              >
                {s.cta}
              </Link>
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}
