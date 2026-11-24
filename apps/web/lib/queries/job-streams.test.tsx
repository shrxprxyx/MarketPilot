import { act, renderHook } from "@testing-library/react";
import type { JobEvent } from "@/lib/api/job-stream";
import { MAX_STREAMS, useJobStreams, type Followable } from "@/lib/queries/job-streams";

type Watch = {
  job: string;
  onEvent: (e: Partial<JobEvent>) => void;
  onDisconnect: () => void;
  stopped: boolean;
};
let watches: Watch[] = [];
vi.mock("@/lib/api/job-stream", () => ({
  isFinished: (s: string) => ["succeeded", "failed", "cancelled"].includes(s),
  watchJob: (job: string, h: Pick<Watch, "onEvent" | "onDisconnect">) => {
    const watch: Watch = { job, ...h, stopped: false };
    watches.push(watch);
    return () => {
      watch.stopped = true;
    };
  },
}));

const target = (n: number): Followable => ({ id: `d${n}`, job_id: `j${n}` });
const open = () => watches.filter((w) => !w.stopped).map((w) => w.job);

beforeEach(() => {
  watches = [];
});

function setup(targets: Followable[]) {
  const onFinished = vi.fn();
  const hook = renderHook((t: Followable[]) => useJobStreams(t, onFinished), {
    initialProps: targets,
  });
  return { ...hook, onFinished };
}

describe("useJobStreams", () => {
  it("reports progress only once a stream actually delivers", () => {
    const { result } = setup([target(1)]);
    expect(result.current).toEqual({}); // connected is not the same as delivering
    act(() => watches[0].onEvent({ status: "running", progress: 30, message: "Embedding" }));
    expect(result.current).toEqual({ d1: { progress: 30, message: "Embedding" } });
  });

  it("drops progress when the connection is lost, so polling takes over", () => {
    const { result } = setup([target(1)]);
    act(() => watches[0].onEvent({ status: "running", progress: 30, message: null }));
    act(() => watches[0].onDisconnect());
    expect(result.current).toEqual({});
  });

  it("asks for a refresh when a job finishes", () => {
    const { result, onFinished } = setup([target(1)]);
    act(() => watches[0].onEvent({ status: "running", progress: 90, message: null }));
    act(() => watches[0].onEvent({ status: "succeeded", progress: 100, message: "Indexed" }));
    expect(onFinished).toHaveBeenCalledTimes(1);
    expect(result.current).toEqual({});
  });

  it(`follows at most ${MAX_STREAMS} jobs, taking the next when one leaves`, () => {
    const all = [1, 2, 3, 4, 5].map(target);
    const { rerender } = setup(all);
    expect(open()).toEqual(["j1", "j2", "j3"]);
    rerender(all.slice(1)); // the first document finished and left the list of targets
    expect(open()).toEqual(["j2", "j3", "j4"]);
  });

  it("does not reconnect streams when the same targets are passed again", () => {
    const { rerender } = setup([target(1), target(2)]);
    rerender([target(1), target(2)]);
    expect(watches).toHaveLength(2);
  });

  it("switches to the new job when a document is re-indexed", () => {
    const { rerender, result } = setup([target(1)]);
    act(() => watches[0].onEvent({ status: "running", progress: 50, message: null }));
    rerender([{ id: "d1", job_id: "j9" }]);
    expect(watches[0].stopped).toBe(true);
    expect(open()).toEqual(["j9"]);
    rerender([]);
    expect(result.current).toEqual({});
  });

  it("closes every stream on unmount", () => {
    const { unmount } = setup([target(1), target(2)]);
    unmount();
    expect(open()).toEqual([]);
  });
});
