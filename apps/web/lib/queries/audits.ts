import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";
import { useJobStreams, type JobProgress } from "@/lib/queries/job-streams";

export type Severity = "critical" | "high" | "medium" | "low";
export const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];

export type AuditStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type Audit = {
  id: string;
  client_id: string;
  type: string;
  url: string;
  status: AuditStatus;
  score: number | null;
  summary: {
    categories?: Record<string, number>;
    severity_counts?: Partial<Record<Severity, number>>;
    pages_crawled?: number;
    truncated?: boolean;
  } | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  job_id?: string | null; // the crawl job, while one is queued or running
};

export type AuditFinding = {
  id: string;
  code: string;
  category: string;
  severity: Severity;
  title: string;
  detail: string;
  url: string | null;
  recommendation: string;
};

export const POLL_MS = 3000;

export const isActive = (a: Pick<Audit, "status">) => a.status === "queued" || a.status === "running";

export function useAudits(clientId: string) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["audits", clientId],
    queryFn: () =>
      apiFetch<{ items: Audit[]; next_cursor: string | null }>(`/clients/${clientId}/audits?limit=20`),
    // The stream reports progress; polling is what notices the audit finishing if it drops.
    refetchInterval: (q) => (q.state.data?.items.some(isActive) ? POLL_MS : false),
  });

  const running = query.data?.items.find((a) => isActive(a) && a.job_id);
  const progress: Record<string, JobProgress> = useJobStreams(
    running?.job_id ? [{ id: running.id, job_id: running.job_id }] : [],
    () => qc.invalidateQueries({ queryKey: ["audits", clientId] }),
  );
  return { ...query, progress };
}

export function useStartAudit(clientId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<Audit>(`/clients/${clientId}/audits`, {
        method: "POST",
        body: JSON.stringify({ type: "website" }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["audits", clientId] }),
  });
}

export function useFindings(auditId: string | undefined, severity: Severity | null) {
  return useQuery({
    queryKey: ["audit-findings", auditId, severity],
    queryFn: () =>
      apiFetch<{ items: AuditFinding[] }>(
        `/audits/${auditId}/findings${severity ? `?severity=${severity}` : ""}`,
      ),
    enabled: !!auditId,
  });
}
