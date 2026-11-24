import { useEffect, useRef, useState } from "react";
import { isFinished, watchJob } from "@/lib/api/job-stream";

// Browsers allow about six HTTP/1.1 connections to one origin, and a stream holds one open.
// Following only a few keeps the rest free for ordinary requests; other documents are polled.
export const MAX_STREAMS = 3;

export type JobProgress = { progress: number; message: string | null };

/** A document with an indexing job that is still in flight. */
export type Followable = { id: string; job_id: string };

/**
 * Follows the indexing jobs of the given documents. Returns live progress by document id,
 * containing only documents whose stream is delivering right now.
 */
export function useJobStreams(
  targets: Followable[],
  onFinished: () => void,
): Record<string, JobProgress> {
  const [live, setLive] = useState<Record<string, JobProgress>>({});
  const streams = useRef(new Map<string, () => void>()); // job id -> stop
  const finished = useRef(onFinished);
  useEffect(() => {
    finished.current = onFinished;
  });

  // A string, so the effect below runs only when the set of jobs changes, not on every refetch.
  const key = targets.map((t) => `${t.id}:${t.job_id}`).join(",");

  useEffect(() => {
    const wanted = key ? key.split(",").map((pair) => pair.split(":")) : [];
    const wantedJobs = new Set(wanted.map(([, job]) => job));
    const drop = (documentId: string) =>
      setLive((current) => {
        if (!(documentId in current)) return current;
        const next = { ...current };
        delete next[documentId];
        return next;
      });

    for (const [job, stop] of streams.current) {
      if (!wantedJobs.has(job)) {
        stop();
        streams.current.delete(job);
      }
    }
    for (const [documentId, job] of wanted) {
      if (streams.current.size >= MAX_STREAMS) break;
      if (streams.current.has(job)) continue;
      streams.current.set(
        job,
        watchJob(job, {
          onEvent: (event) => {
            if (isFinished(event.status)) {
              drop(documentId);
              finished.current();
              return;
            }
            setLive((current) => ({
              ...current,
              [documentId]: { progress: event.progress, message: event.message },
            }));
          },
          onDisconnect: () => drop(documentId),
        }),
      );
    }
  }, [key]);

  useEffect(() => {
    const open = streams.current;
    return () => {
      for (const stop of open.values()) stop();
      open.clear();
    };
  }, []);

  // Never report progress for a document that is no longer being followed.
  const ids = new Set(targets.map((t) => t.id));
  return Object.fromEntries(Object.entries(live).filter(([id]) => ids.has(id)));
}
