"use client";

import { RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { FormError } from "@/components/auth/auth-card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ApiError } from "@/lib/api/problem";
import {
  useDeleteDocument,
  useReindexDocument,
  type DocStatus,
  type KnowledgeDoc,
} from "@/lib/queries/documents";

const SOURCE_LABELS: Record<string, string> = {
  upload: "Upload",
  brand_doc: "Brand doc",
  past_content: "Past content",
};

// Colour is never the only signal: every status also has its own text.
function StatusBadge({ status }: { status: DocStatus }) {
  if (status === "ready") {
    return (
      <Badge variant="outline" className="border-emerald-500/40 text-emerald-300">
        Ready
      </Badge>
    );
  }
  if (status === "failed") return <Badge variant="destructive">Failed</Badge>;
  return <Badge variant="secondary">Indexing…</Badge>;
}

const detailOf = (e: unknown) =>
  e instanceof ApiError ? e.detail : "Something went wrong. Please try again.";

export function DocumentRow({
  doc,
  canWrite,
  clientId,
}: {
  doc: KnowledgeDoc;
  canWrite: boolean;
  clientId: string;
}) {
  const reindex = useReindexDocument(clientId);
  const remove = useDeleteDocument(clientId);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function runReindex() {
    setError(null);
    try {
      await reindex.mutateAsync(doc.id);
      toast.success("Re-indexing started");
    } catch (e) {
      setError(detailOf(e));
    }
  }

  async function confirmDelete() {
    setDeleteError(null);
    try {
      await remove.mutateAsync(doc.id);
      toast.success("Document deleted");
      setConfirming(false);
    } catch (e) {
      setDeleteError(detailOf(e));
    }
  }

  return (
    <li className="flex flex-col gap-2 py-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate font-medium">{doc.title}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {SOURCE_LABELS[doc.source_type] ?? doc.source_type}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={doc.status} />
          {canWrite && (
            <>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Re-index ${doc.title}`}
                onClick={runReindex}
              >
                <RefreshCw className="size-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Delete ${doc.title}`}
                onClick={() => setConfirming(true)}
              >
                <Trash2 className="size-4" />
              </Button>
            </>
          )}
        </div>
      </div>
      {doc.status === "failed" && doc.error && (
        <p className="text-sm text-destructive">{doc.error}</p>
      )}
      <FormError message={error} />
      <Dialog
        open={confirming}
        onOpenChange={(next) => {
          setConfirming(next);
          if (!next) setDeleteError(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {doc.title}?</DialogTitle>
            <DialogDescription>
              Its indexed content is removed and can no longer be used as a source.
            </DialogDescription>
          </DialogHeader>
          <FormError message={deleteError} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              Delete document
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  );
}
