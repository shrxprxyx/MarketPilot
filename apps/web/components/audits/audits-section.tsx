"use client";

import { useState } from "react";
import { FormError } from "@/components/auth/auth-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/problem";
import { useSession } from "@/lib/auth/session-store";
import {
  isActive,
  SEVERITIES,
  useAudits,
  useFindings,
  useStartAudit,
  type Audit,
  type Severity,
} from "@/lib/queries/audits";
import type { JobProgress } from "@/lib/queries/job-streams";

const CATEGORY_LABELS: Record<string, string> = {
  technical: "Technical",
  on_page: "On-page",
  links: "Links",
  mobile: "Mobile",
};

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

function Progress({ progress, message }: Partial<JobProgress>) {
  return (
    <div className="flex flex-col gap-1.5">
      <div
        role="progressbar"
        aria-label="Audit progress"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress ?? 0}
        className="h-1 w-full overflow-hidden rounded-full bg-white/10"
      >
        <div className="h-full bg-emerald-400 transition-[width]" style={{ width: `${progress ?? 0}%` }} />
      </div>
      <p aria-live="polite" className="text-xs text-muted-foreground">
        {message ?? "Waiting to start"}
      </p>
    </div>
  );
}

function Score({ audit }: { audit: Audit }) {
  const categories = Object.entries(audit.summary?.categories ?? {});
  return (
    <div className="flex flex-wrap items-end gap-8">
      <p className="font-heading text-6xl font-semibold leading-none">
        {audit.score}
        <span className="ml-1 text-lg font-normal text-muted-foreground">/ 100</span>
      </p>
      <dl className="flex flex-wrap gap-6">
        {categories.map(([name, value]) => (
          <div key={name}>
            <dt className="text-xs text-muted-foreground">{CATEGORY_LABELS[name] ?? name}</dt>
            <dd className="text-lg font-medium">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Findings({ audit }: { audit: Audit }) {
  const [severity, setSeverity] = useState<Severity | null>(null);
  const { data, isLoading, isError } = useFindings(audit.id, severity);
  const counts = audit.summary?.severity_counts ?? {};
  const total = SEVERITIES.reduce((n, s) => n + (counts[s] ?? 0), 0);
  const items = data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div role="group" aria-label="Filter findings by severity" className="flex flex-wrap gap-2">
        <Button
          size="sm"
          variant={severity === null ? "default" : "outline"}
          aria-pressed={severity === null}
          onClick={() => setSeverity(null)}
        >
          All ({total})
        </Button>
        {SEVERITIES.map((s) => (
          <Button
            key={s}
            size="sm"
            variant={severity === s ? "default" : "outline"}
            aria-pressed={severity === s}
            onClick={() => setSeverity(s)}
          >
            {cap(s)} ({counts[s] ?? 0})
          </Button>
        ))}
      </div>
      {isLoading ? (
        <Skeleton data-testid="findings-skeleton" className="h-14 w-full" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">Couldn&apos;t load findings. Try again later.</p>
      ) : items.length === 0 ? (
        <p className="border-y py-10 text-sm text-muted-foreground">
          {severity ? `No ${severity} findings` : "No issues found"}
        </p>
      ) : (
        <ul className="divide-y border-y">
          {items.map((f) => (
            <li key={f.id} className="flex flex-col gap-1.5 py-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant={f.severity === "critical" || f.severity === "high" ? "destructive" : "secondary"}>
                  {cap(f.severity)}
                </Badge>
                <span className="font-medium">{f.title}</span>
              </div>
              {f.url && <p className="break-all font-mono text-xs text-muted-foreground">{f.url}</p>}
              <p className="text-sm text-muted-foreground">{f.detail}</p>
              <p className="text-sm">
                <span className="text-muted-foreground">Fix: </span>
                {f.recommendation}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function AuditsSection({ clientId }: { clientId: string }) {
  const role = useSession((s) => s.me?.role);
  const canWrite = role === "admin" || role === "manager";
  const { data, isLoading, isError, progress } = useAudits(clientId);
  const start = useStartAudit(clientId);
  const [error, setError] = useState<string | null>(null);

  const latest = data?.items[0];
  const active = !!latest && isActive(latest);

  async function run() {
    setError(null);
    try {
      await start.mutateAsync();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Something went wrong. Please try again.");
    }
  }

  return (
    <section className="flex max-w-4xl flex-col gap-8">
      <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
        Crawls this client&apos;s website and scores its technical health, on-page SEO and links, with
        a fix for every issue.
      </p>

      {canWrite && (
        <div className="flex flex-col gap-3">
          <div>
            <Button className="h-11 cursor-pointer px-4" disabled={start.isPending || active} onClick={run}>
              {active ? "Audit running…" : latest ? "Run a new audit" : "Run audit"}
            </Button>
          </div>
          <FormError message={error} />
        </div>
      )}

      {isLoading ? (
        <Skeleton data-testid="audit-skeleton" className="h-24 w-full" />
      ) : isError ? (
        <p className="text-sm text-muted-foreground">Couldn&apos;t load audits. Try again later.</p>
      ) : !latest ? (
        <p className="border-y py-10 text-sm text-muted-foreground">No audits yet</p>
      ) : active ? (
        <Progress {...progress[latest.id]} />
      ) : latest.status === "succeeded" ? (
        <>
          <p className="text-xs text-muted-foreground">
            {latest.url} · {latest.summary?.pages_crawled ?? 0} pages crawled
            {latest.summary?.truncated ? " (limit reached)" : ""}
          </p>
          <Score audit={latest} />
          <Findings audit={latest} />
        </>
      ) : (
        <FormError
          message={
            latest.status === "cancelled" ? "The audit was cancelled." : (latest.error ?? "The audit failed.")
          }
        />
      )}
    </section>
  );
}
