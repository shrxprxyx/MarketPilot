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
  useComparison,
  useFindings,
  useStartAudit,
  type Audit,
  type AuditFinding,
  type Severity,
} from "@/lib/queries/audits";
import type { JobProgress } from "@/lib/queries/job-streams";

const CATEGORY_LABELS: Record<string, string> = {
  technical: "Technical",
  on_page: "On-page",
  links: "Links",
  mobile: "Mobile",
};

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  running: "Running",
  failed: "Failed",
  cancelled: "Cancelled",
};

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });

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

function FindingItem({ f }: { f: AuditFinding }) {
  return (
    <li className="flex flex-col gap-1.5 py-4">
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
  );
}

const CHANGES = ["new", "fixed", "unchanged"] as const;
type Change = (typeof CHANGES)[number];

function Comparison({ audit }: { audit: Audit }) {
  const { data, isLoading, isError } = useComparison(audit.id);
  const [change, setChange] = useState<Change>("new");

  if (isLoading) return <Skeleton data-testid="comparison-skeleton" className="h-10 w-full" />;
  if (isError || !data) {
    return <p className="text-sm text-muted-foreground">Couldn&apos;t compare with the previous audit.</p>;
  }
  if (!data.previous) {
    return (
      <p className="text-sm text-muted-foreground">
        This is the first audit for this client, so there is nothing to compare it with yet.
      </p>
    );
  }
  const diff =
    audit.score !== null && data.previous.score !== null ? audit.score - data.previous.score : null;
  const items = data[change];

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Compared with the audit of {when(data.previous.created_at)}
        {diff !== null && (
          <>
            {" "}
            (score {data.previous.score},{" "}
            {diff === 0 ? "no change" : `${diff > 0 ? "+" : "−"}${Math.abs(diff)}`})
          </>
        )}
      </p>
      <div role="group" aria-label="Changes since the previous audit" className="flex flex-wrap gap-2">
        {CHANGES.map((c) => (
          <Button
            key={c}
            size="sm"
            variant={change === c ? "default" : "outline"}
            aria-pressed={change === c}
            onClick={() => setChange(c)}
          >
            {cap(c)} ({data[c].length})
          </Button>
        ))}
      </div>
      {items.length === 0 ? (
        <p className="border-y py-10 text-sm text-muted-foreground">No {change} issues</p>
      ) : (
        <ul className="divide-y border-y">
          {items.map((f) => (
            <FindingItem key={f.id} f={f} />
          ))}
        </ul>
      )}
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
      <h3 className="text-sm font-medium">All findings</h3>
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
            <FindingItem key={f.id} f={f} />
          ))}
        </ul>
      )}
    </div>
  );
}

function History({
  audits,
  shownId,
  onSelect,
}: {
  audits: Audit[];
  shownId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <nav aria-label="Audit history" className="flex flex-col gap-2">
      <h3 className="text-sm font-medium">History</h3>
      <ul className="divide-y border-y">
        {audits.map((a) => (
          <li key={a.id}>
            <button
              type="button"
              aria-current={a.id === shownId ? "true" : undefined}
              onClick={() => onSelect(a.id)}
              className="flex w-full cursor-pointer items-center justify-between gap-4 px-1 py-3 text-left text-sm hover:bg-muted/50 aria-[current=true]:bg-muted"
            >
              <span>{when(a.created_at)}</span>
              <span className="text-muted-foreground">
                {a.status === "succeeded" ? `Score ${a.score}` : STATUS_LABELS[a.status]}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function AuditsSection({ clientId }: { clientId: string }) {
  const role = useSession((s) => s.me?.role);
  const canWrite = role === "admin" || role === "manager";
  const { data, isLoading, isError, progress } = useAudits(clientId);
  const start = useStartAudit(clientId);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const audits = data?.items ?? [];
  const latest = audits[0];
  const shown = audits.find((a) => a.id === selected) ?? latest;
  const active = !!latest && isActive(latest);

  async function run() {
    setError(null);
    try {
      await start.mutateAsync();
      setSelected(null); // show the new audit
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Something went wrong. Please try again.");
    }
  }

  return (
    <section className="flex max-w-4xl flex-col gap-8">
      <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
        Crawls this client&apos;s website and scores its technical health, on-page SEO and links, with a fix
        for every issue.
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
      ) : !shown ? (
        <p className="border-y py-10 text-sm text-muted-foreground">No audits yet</p>
      ) : (
        <>
          {isActive(shown) ? (
            <Progress {...progress[shown.id]} />
          ) : shown.status === "succeeded" ? (
            <>
              <p className="text-xs text-muted-foreground">
                {shown.url} · {when(shown.created_at)} · {shown.summary?.pages_crawled ?? 0} pages crawled
                {shown.summary?.truncated ? " (limit reached)" : ""}
              </p>
              <Score audit={shown} />
              <Comparison key={`compare-${shown.id}`} audit={shown} />
              <Findings key={shown.id} audit={shown} />
            </>
          ) : (
            <FormError
              message={
                shown.status === "cancelled"
                  ? "The audit was cancelled."
                  : (shown.error ?? "The audit failed.")
              }
            />
          )}
          {audits.length > 1 && <History audits={audits} shownId={shown.id} onSelect={setSelected} />}
          {data?.next_cursor && (
            <p className="text-sm text-muted-foreground">Showing the latest {audits.length} audits</p>
          )}
        </>
      )}
    </section>
  );
}
