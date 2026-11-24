import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "@/lib/api/client";
import { useJobStreams, type Followable, type JobProgress } from "@/lib/queries/job-streams";

export type DocStatus = "pending" | "processing" | "ready" | "failed";

export type KnowledgeDoc = {
  id: string;
  client_id: string;
  source_type: string;
  title: string;
  status: DocStatus;
  error: string | null;
  job_id?: string | null; // the indexing job, while one is queued or running
};

export type DocumentList = { items: KnowledgeDoc[]; next_cursor: string | null };
export type AddedDocument = KnowledgeDoc & { duplicate: boolean };

export const FAST_POLL_MS = 2000;
// While every in-flight document is streaming, this only guards against a lost final event.
export const SAFETY_POLL_MS = 15000;

const inFlight = (d: KnowledgeDoc) => d.status === "pending" || d.status === "processing";

/**
 * Indexing runs in the worker. Job streams report its progress; polling covers everything they
 * do not: every 2s while any in-flight document has no delivering stream (none yet, no job, over
 * the stream cap, or the connection dropped), slowly when all of them do, and not at all once
 * nothing is in flight. The worker sets "processing" while it runs, so that counts too.
 */
export function pollWhilePending(
  data: DocumentList | undefined,
  streaming: Record<string, JobProgress> = {},
): number | false {
  const waiting = data?.items.filter(inFlight) ?? [];
  if (waiting.length === 0) return false;
  return waiting.every((d) => d.id in streaming) ? SAFETY_POLL_MS : FAST_POLL_MS;
}

export function useDocuments(clientId: string) {
  const qc = useQueryClient();
  const [streaming, setStreaming] = useState<Record<string, JobProgress>>({});
  const query = useQuery({
    queryKey: ["documents", clientId],
    queryFn: () => apiFetch<DocumentList>(`/clients/${clientId}/documents?limit=100`),
    refetchInterval: (q) => pollWhilePending(q.state.data, streaming),
  });

  const targets: Followable[] = (query.data?.items ?? []).flatMap((d) =>
    inFlight(d) && d.job_id ? [{ id: d.id, job_id: d.job_id }] : [],
  );
  const progress = useJobStreams(targets, () =>
    qc.invalidateQueries({ queryKey: ["documents", clientId] }),
  );

  // The poll interval is decided inside useQuery above, before the streams are known, so which
  // documents are streaming is mirrored into state. It is updated only when that set changes.
  const idsOf = (r: Record<string, JobProgress>) => Object.keys(r).sort().join(",");
  if (idsOf(progress) !== idsOf(streaming)) setStreaming(progress);

  return { ...query, progress };
}

function useDocumentMutation<V, R>(clientId: string, fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["documents", clientId] }),
  });
}

export function useUploadDocument(clientId: string) {
  return useDocumentMutation(clientId, (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return apiFetch<AddedDocument>(`/clients/${clientId}/documents`, { method: "POST", body: form });
  });
}

export function usePasteDocument(clientId: string) {
  return useDocumentMutation(clientId, (v: { title: string; text: string }) =>
    apiFetch<AddedDocument>(`/clients/${clientId}/documents`, {
      method: "POST",
      body: JSON.stringify({ ...v, source_type: "brand_doc" }),
    }),
  );
}

export function useReindexDocument(clientId: string) {
  return useDocumentMutation(clientId, (docId: string) =>
    apiFetch<KnowledgeDoc>(`/documents/${docId}/reindex`, { method: "POST" }),
  );
}

export function useDeleteDocument(clientId: string) {
  return useDocumentMutation(clientId, (docId: string) =>
    apiFetch<void>(`/documents/${docId}`, { method: "DELETE" }),
  );
}
