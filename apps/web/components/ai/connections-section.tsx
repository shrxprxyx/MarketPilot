"use client";

import { Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { AddConnectionDialog } from "@/components/ai/add-connection-dialog";
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
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/problem";
import {
  useAiConnections,
  useDeleteConnection,
  useTestConnection,
  type AiConnection,
} from "@/lib/queries/ai";

const detailOf = (e: unknown) =>
  e instanceof ApiError ? e.detail : "Something went wrong. Please try again.";

function ConnectionRow({
  conn,
  models,
  onTested,
}: {
  conn: AiConnection;
  models: string[] | undefined;
  onTested: (connectionId: string, models: string[]) => void;
}) {
  const testConn = useTestConnection();
  const remove = useDeleteConnection();
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function runTest() {
    setTesting(true);
    setError(null);
    try {
      const result = await testConn.mutateAsync(conn.id);
      onTested(conn.id, result.models);
    } catch (e) {
      setError(detailOf(e));
    } finally {
      setTesting(false);
    }
  }

  async function confirmDelete() {
    setDeleteError(null);
    try {
      await remove.mutateAsync(conn.id);
      toast.success("Connection deleted");
      setConfirming(false);
    } catch (e) {
      setDeleteError(detailOf(e));
    }
  }

  return (
    <li className="flex flex-col gap-3 py-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <p className="truncate font-medium">{conn.label}</p>
            <Badge variant="outline" data-provider>
              {conn.provider}
            </Badge>
          </div>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            {conn.key_last4 ? `••••${conn.key_last4}` : (conn.base_url ?? "No key")}
            {models && ` · ${models.length} models`}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            aria-label={`Test ${conn.label}`}
            disabled={testing}
            onClick={runTest}
          >
            {testing ? "Testing…" : "Test"}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`Delete ${conn.label}`}
            onClick={() => setConfirming(true)}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      </div>
      <FormError message={error} />
      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete {conn.label}?</DialogTitle>
            <DialogDescription>
              Tasks routed through this connection will stop working until you choose another.
            </DialogDescription>
          </DialogHeader>
          <FormError message={deleteError} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDelete}>
              Delete connection
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </li>
  );
}

export function ConnectionsSection({
  testedModels,
  onTested,
}: {
  testedModels: Record<string, string[]>;
  onTested: (connectionId: string, models: string[]) => void;
}) {
  const { data, isLoading, isError } = useAiConnections(true);

  return (
    <section>
      <div className="mb-5 flex items-center justify-between">
        <h2 className="font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
          Connections
        </h2>
        {data && data.length > 0 && <AddConnectionDialog variant="outline" />}
      </div>
      {isLoading ? (
        <div className="flex flex-col gap-4">
          {[0, 1].map((i) => (
            <Skeleton key={i} data-testid="connection-skeleton" className="h-14 w-full" />
          ))}
        </div>
      ) : isError ? (
        <p className="text-sm text-muted-foreground">Couldn&apos;t load connections. Try again later.</p>
      ) : data && data.length > 0 ? (
        <ul className="divide-y border-y">
          {data.map((c) => (
            <ConnectionRow key={c.id} conn={c} models={testedModels[c.id]} onTested={onTested} />
          ))}
        </ul>
      ) : (
        <div className="border-y py-10">
          <p className="text-sm text-muted-foreground">
            No connections yet. Add your own OpenAI, Anthropic, Ollama or compatible endpoint to
            start using AI.
          </p>
          <div className="mt-5">
            <AddConnectionDialog />
          </div>
        </div>
      )}
    </section>
  );
}
