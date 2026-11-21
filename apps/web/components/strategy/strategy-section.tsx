"use client";

import Link from "next/link";
import { useState } from "react";
import { Field, FormError } from "@/components/auth/auth-card";
import { StrategyView } from "@/components/strategy/strategy-view";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/problem";
import { useSession } from "@/lib/auth/session-store";
import { useGenerateStrategy, useStrategies, type Strategy } from "@/lib/queries/strategies";

const currentMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

export function StrategySection({ clientId }: { clientId: string }) {
  const role = useSession((s) => s.me?.role);
  const canWrite = role === "admin" || role === "manager";
  const { data, isLoading, isError } = useStrategies(clientId);
  const generate = useGenerateStrategy(clientId);
  const [month, setMonth] = useState(currentMonth);
  const [picked, setPicked] = useState<Strategy | null>(null);
  const [error, setError] = useState<{ status: number; detail: string } | null>(null);

  const items = data ?? [];
  const shown = picked ?? items[0];
  const hasMonth = items.some((s) => s.month === month);

  async function run() {
    setError(null);
    try {
      setPicked(await generate.mutateAsync({ month }));
    } catch (e) {
      setError(
        e instanceof ApiError
          ? { status: e.status, detail: e.detail }
          : { status: 0, detail: "Something went wrong. Please try again." },
      );
    }
  }

  return (
    <section className="flex max-w-4xl flex-col gap-8">
      <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
        A monthly plan written by your own AI model from this client&apos;s brand profile and
        knowledge, with the sources it used.
      </p>

      {canWrite && (
        <div className="flex flex-wrap items-end gap-4">
          <div className="w-44">
            <Field
              id="strategy-month"
              label="Month"
              type="month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
            />
          </div>
          <Button
            className="h-11 cursor-pointer px-4"
            disabled={generate.isPending || !month}
            onClick={run}
          >
            {generate.isPending ? "Generating…" : hasMonth ? "Regenerate" : "Generate strategy"}
          </Button>
        </div>
      )}
      <div role="status" className="text-sm text-muted-foreground">
        {generate.isPending && "Generating your strategy. This can take up to a minute."}
      </div>
      {error && (
        <div className="flex flex-col gap-2">
          <FormError message={error.detail} />
          {error.status === 409 && (
            <Link
              href="/settings/ai"
              className="w-fit text-sm underline underline-offset-4 hover:text-foreground"
            >
              Open AI models
            </Link>
          )}
        </div>
      )}

      {isLoading ? (
        <Skeleton data-testid="strategy-skeleton" className="h-40 w-full" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">Couldn&apos;t load strategies. Try again later.</p>
      ) : items.length === 0 ? (
        <p className="border-y py-10 text-sm text-muted-foreground">No strategies yet</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            {items.map((s) => (
              <Button
                key={s.id}
                variant="outline"
                size="sm"
                className="cursor-pointer"
                aria-pressed={shown?.id === s.id}
                onClick={() => setPicked(s)}
              >
                {s.month} · v{s.version}
              </Button>
            ))}
          </div>
          {shown && <StrategyView strategy={shown} />}
        </>
      )}
    </section>
  );
}
