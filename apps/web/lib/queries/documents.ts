import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api/client";

export type DocStatus = "pending" | "processing" | "ready" | "failed";

export type KnowledgeDoc = {
  id: string;
  client_id: string;
  source_type: string;
  title: string;
  status: DocStatus;
  error: string | null;
};

export type DocumentList = { items: KnowledgeDoc[]; next_cursor: string | null };
export type AddedDocument = KnowledgeDoc & { duplicate: boolean };

/**
 * Indexing runs in the worker: refetch every 2s while anything is queued or being indexed,
 * then stop. The worker sets "processing" while it runs, so that counts as in flight too.
 */
export function pollWhilePending(data: DocumentList | undefined): number | false {
  return data?.items.some((d) => d.status === "pending" || d.status === "processing")
    ? 2000
    : false;
}

export function useDocuments(clientId: string) {
  return useQuery({
    queryKey: ["documents", clientId],
    queryFn: () => apiFetch<DocumentList>(`/clients/${clientId}/documents?limit=100`),
    refetchInterval: (query) => pollWhilePending(query.state.data),
  });
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
