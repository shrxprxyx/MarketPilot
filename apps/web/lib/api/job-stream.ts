import { apiFetch } from "@/lib/api/client";

export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export type JobEvent = {
  job_id: string;
  type: string;
  status: JobStatus;
  progress: number;
  message: string | null;
  error: string | null;
  result_ref: Record<string, unknown> | null;
};

export const MAX_RETRIES = 3;
const FIRST_RETRY_MS = 1000;
const FINISHED: JobStatus[] = ["succeeded", "failed", "cancelled"];

export const isFinished = (status: JobStatus) => FINISHED.includes(status);

type Handlers = {
  onEvent: (event: JobEvent) => void;
  /** The connection dropped (or could not be opened): stop trusting the last event. */
  onDisconnect: () => void;
};

/**
 * Follows one job over Server-Sent Events until it finishes. Returns a function that stops.
 *
 * EventSource cannot send an Authorization header, so each connection first asks for a
 * single-use ticket. That is also why its built-in reconnect is not used: it would replay a
 * spent ticket. This reconnects itself with a new ticket, a few times with backoff, then gives
 * up. Callers keep polling whenever the stream is not delivering, so giving up loses nothing.
 */
export function watchJob(jobId: string, { onEvent, onDisconnect }: Handlers): () => void {
  if (typeof EventSource === "undefined") return () => {};

  let source: EventSource | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let failures = 0;
  let stopped = false;

  function stop() {
    stopped = true;
    clearTimeout(timer);
    source?.close();
    source = null;
  }

  function retry() {
    source?.close();
    source = null;
    if (stopped) return;
    onDisconnect();
    failures += 1;
    if (failures > MAX_RETRIES) return;
    timer = setTimeout(connect, FIRST_RETRY_MS * 2 ** (failures - 1));
  }

  async function connect() {
    let ticket: string;
    try {
      ({ ticket } = await apiFetch<{ ticket: string }>("/auth/stream-ticket", {
        method: "POST",
      }));
    } catch {
      retry();
      return;
    }
    if (stopped) return;
    source = new EventSource(
      `/api/jobs/${encodeURIComponent(jobId)}/events?ticket=${encodeURIComponent(ticket)}`,
    );
    source.addEventListener("job", (message) => {
      let event: JobEvent;
      try {
        event = JSON.parse((message as MessageEvent<string>).data) as JobEvent;
      } catch {
        return; // a garbled frame is ignored; the next one carries the full state again
      }
      failures = 0;
      if (isFinished(event.status)) stop();
      onEvent(event);
    });
    source.onerror = retry;
  }

  void connect();
  return stop;
}
