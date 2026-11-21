"use client";

import { useState } from "react";
import { toast } from "sonner";
import { FormError } from "@/components/auth/auth-card";
import { EditClientDialog } from "@/components/clients/edit-client-dialog";
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
import { useSession } from "@/lib/auth/session-store";
import { useArchiveClient, useUpdateClient, type Client } from "@/lib/queries/clients";

const detailOf = (e: unknown) =>
  e instanceof ApiError ? e.detail : "Something went wrong. Please try again.";

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="py-4">
      <dt className="font-mono text-[11px] uppercase tracking-[0.14em] text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1.5 text-sm">{children}</dd>
    </div>
  );
}

export function ClientOverview({ client }: { client: Client }) {
  const role = useSession((s) => s.me?.role);
  const canWrite = role === "admin" || role === "manager";
  const update = useUpdateClient(client.id);
  const archive = useArchiveClient(client.id);
  const [confirming, setConfirming] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const archived = client.status === "archived";

  async function confirmArchive() {
    setArchiveError(null);
    try {
      await archive.mutateAsync();
      toast.success("Client archived");
      setConfirming(false);
    } catch (e) {
      setArchiveError(detailOf(e));
    }
  }

  async function restore() {
    setRestoreError(null);
    try {
      await update.mutateAsync({ status: "active" });
      toast.success("Client restored");
    } catch (e) {
      setRestoreError(detailOf(e));
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <dl className="grid divide-y border-y sm:grid-cols-2 sm:divide-y-0 sm:[&>div]:border-b">
        <Detail label="Status">
          <Badge variant="outline">{client.status}</Badge>
        </Detail>
        <Detail label="Industry">{client.industry ?? "No industry set"}</Detail>
        <Detail label="Website">
          {client.website_url ? (
            <a
              href={client.website_url}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all text-foreground underline underline-offset-4"
            >
              {client.website_url}
            </a>
          ) : (
            "No website"
          )}
        </Detail>
        <Detail label="Goals">
          {client.goals && client.goals.length > 0 ? (
            <ul className="list-disc pl-5">
              {client.goals.map((g) => (
                <li key={g}>{g}</li>
              ))}
            </ul>
          ) : (
            "No goals yet"
          )}
        </Detail>
      </dl>

      {canWrite && (
        <div className="flex flex-wrap gap-3">
          <EditClientDialog client={client} />
          {archived ? (
            <Button variant="outline" className="h-10 px-4" onClick={restore}>
              Restore
            </Button>
          ) : (
            <Button variant="outline" className="h-10 px-4" onClick={() => setConfirming(true)}>
              Archive
            </Button>
          )}
        </div>
      )}
      <FormError message={restoreError} />

      <Dialog
        open={confirming}
        onOpenChange={(next) => {
          setConfirming(next);
          if (!next) setArchiveError(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Archive {client.name}?</DialogTitle>
            <DialogDescription>
              The client stays in your list marked as archived, and its documents and history are
              kept. It can be restored at any time.
            </DialogDescription>
          </DialogHeader>
          <FormError message={archiveError} />
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmArchive}>
              Archive client
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
