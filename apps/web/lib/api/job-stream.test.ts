import { MAX_RETRIES, watchJob, type JobEvent } from "@/lib/api/job-stream";

let tickets = 0;
let ticketFails = false;
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string, init?: RequestInit) => {
    expect(path).toBe("/auth/stream-ticket");
    expect(init?.method).toBe("POST");
    if (ticketFails) throw new Error("offline");
    tickets += 1;
    return { ticket: `t${tickets}` };
  },
}));

class FakeEventSource {
  static opened: FakeEventSource[] = [];
  closed = false;
  onerror: (() => void) | null = null;
  private listener: ((e: { data: string }) => void) | null = null;
  constructor(public url: string) {
    FakeEventSource.opened.push(this);
  }
  addEventListener(name: string, fn: (e: { data: string }) => void) {
    if (name === "job") this.listener = fn;
  }
  close() {
    this.closed = true;
  }
  emit(event: Partial<JobEvent> | string) {
    this.listener?.({ data: typeof event === "string" ? event : JSON.stringify(event) });
  }
}

const last = () => FakeEventSource.opened.at(-1)!;
const flush = () => vi.advanceTimersByTimeAsync(0);

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", FakeEventSource);
  FakeEventSource.opened = [];
  tickets = 0;
  ticketFails = false;
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const handlers = () => ({ onEvent: vi.fn(), onDisconnect: vi.fn() });

describe("watchJob", () => {
  it("opens the stream with a fresh ticket and passes events on", async () => {
    const h = handlers();
    watchJob("job-1", h);
    await flush();
    expect(last().url).toBe("/api/jobs/job-1/events?ticket=t1");
    last().emit({ status: "running", progress: 40 });
    expect(h.onEvent).toHaveBeenCalledWith({ status: "running", progress: 40 });
  });

  it("closes the stream once the job finishes", async () => {
    const h = handlers();
    watchJob("job-1", h);
    await flush();
    last().emit({ status: "succeeded", progress: 100 });
    expect(last().closed).toBe(true);
    last().onerror?.(); // the server closing the connection afterwards must not reconnect
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeEventSource.opened).toHaveLength(1);
    expect(h.onDisconnect).not.toHaveBeenCalled();
  });

  it("reconnects with a new ticket, because tickets work only once", async () => {
    const h = handlers();
    watchJob("job-1", h);
    await flush();
    last().onerror?.();
    expect(FakeEventSource.opened[0].closed).toBe(true); // stops EventSource's own retry
    expect(h.onDisconnect).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(last().url).toBe("/api/jobs/job-1/events?ticket=t2");
  });

  it("gives up after a few failures in a row", async () => {
    watchJob("job-1", handlers());
    for (let i = 0; i <= MAX_RETRIES; i += 1) {
      await vi.advanceTimersByTimeAsync(10_000);
      last().onerror?.();
    }
    await vi.advanceTimersByTimeAsync(120_000);
    expect(FakeEventSource.opened).toHaveLength(MAX_RETRIES + 1);
  });

  it("resets the failure count once events arrive again", async () => {
    watchJob("job-1", handlers());
    for (let i = 0; i < MAX_RETRIES * 2; i += 1) {
      await vi.advanceTimersByTimeAsync(10_000);
      last().emit({ status: "running", progress: i });
      last().onerror?.();
    }
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeEventSource.opened).toHaveLength(MAX_RETRIES * 2 + 1);
  });

  it("retries when a ticket cannot be issued", async () => {
    ticketFails = true;
    const h = handlers();
    watchJob("job-1", h);
    await flush();
    expect(FakeEventSource.opened).toHaveLength(0);
    expect(h.onDisconnect).toHaveBeenCalled();
    ticketFails = false;
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeEventSource.opened).toHaveLength(1);
  });

  it("stops cleanly, even while the ticket request is still pending", async () => {
    const stop = watchJob("job-1", handlers());
    stop();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeEventSource.opened).toHaveLength(0);
  });

  it("ignores a garbled frame", async () => {
    const h = handlers();
    watchJob("job-1", h);
    await flush();
    last().emit("{not json");
    expect(h.onEvent).not.toHaveBeenCalled();
    expect(last().closed).toBe(false);
  });

  it("does nothing where EventSource does not exist", async () => {
    vi.stubGlobal("EventSource", undefined);
    watchJob("job-1", handlers());
    await flush();
    expect(tickets).toBe(0);
  });
});
