"use client";

import { AddDocumentPanel } from "@/components/knowledge/add-document-panel";
import { DocumentRow } from "@/components/knowledge/document-row";
import { Skeleton } from "@/components/ui/skeleton";
import { useSession } from "@/lib/auth/session-store";
import { useDocuments } from "@/lib/queries/documents";

const LIMIT = 100;

export function KnowledgeSection({ clientId }: { clientId: string }) {
  const role = useSession((s) => s.me?.role);
  const canWrite = role === "admin" || role === "manager";
  const { data, isLoading, isError, progress } = useDocuments(clientId);
  const items = data?.items ?? [];

  return (
    <section className="flex max-w-4xl flex-col gap-8">
      <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
        Documents here are indexed so AI can use this client&apos;s own material as grounded sources.
      </p>
      {canWrite && <AddDocumentPanel clientId={clientId} />}
      {isLoading ? (
        <div className="flex flex-col gap-3">
          {[0, 1].map((i) => (
            <Skeleton key={i} data-testid="doc-skeleton" className="h-14 w-full" />
          ))}
        </div>
      ) : isError ? (
        <p className="text-sm text-muted-foreground">Couldn&apos;t load documents. Try again later.</p>
      ) : items.length === 0 ? (
        <p className="border-y py-10 text-sm text-muted-foreground">No documents yet</p>
      ) : (
        <>
          <ul className="divide-y border-y">
            {items.map((d) => (
              <DocumentRow
                key={d.id}
                doc={d}
                canWrite={canWrite}
                clientId={clientId}
                progress={progress?.[d.id]}
              />
            ))}
          </ul>
          {data?.next_cursor && (
            <p className="text-sm text-muted-foreground">Showing the first {LIMIT} documents</p>
          )}
        </>
      )}
    </section>
  );
}
