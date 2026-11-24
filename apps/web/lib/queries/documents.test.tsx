import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import {
  pollWhilePending,
  useDeleteDocument,
  useDocuments,
  usePasteDocument,
  useReindexDocument,
  useUploadDocument,
  type DocStatus,
  type DocumentList,
} from "@/lib/queries/documents";

const calls: { path: string; init?: RequestInit }[] = [];
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    return { items: [], next_cursor: null };
  },
}));

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  calls.length = 0;
});

const doc = (status: DocStatus) => ({
  id: "d",
  client_id: "c1",
  source_type: "upload",
  title: "t",
  status,
  error: null,
});
const list = (...statuses: DocStatus[]): DocumentList => ({
  items: statuses.map(doc),
  next_cursor: null,
});

describe("pollWhilePending", () => {
  it("polls every 2 seconds while any document is pending", () => {
    expect(pollWhilePending(list("ready", "pending"))).toBe(2000);
  });
  it("keeps polling while a document is being indexed", () => {
    // The worker flips pending -> processing; stopping here would freeze the row mid-indexing.
    expect(pollWhilePending(list("ready", "processing"))).toBe(2000);
  });
  it("stops when nothing is pending", () => {
    expect(pollWhilePending(list("ready", "failed"))).toBe(false);
    expect(pollWhilePending(list())).toBe(false);
    expect(pollWhilePending(undefined)).toBe(false);
  });
});

describe("document hooks", () => {
  it("lists a client's documents with limit 100", async () => {
    renderHook(() => useDocuments("c1"), { wrapper });
    await waitFor(() => expect(calls.map((c) => c.path)).toEqual(["/clients/c1/documents?limit=100"]));
  });

  it("uploads a file as multipart FormData under the file field", async () => {
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    const { result } = renderHook(() => useUploadDocument("c1"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync(file);
    });
    expect(calls[0].path).toBe("/clients/c1/documents");
    expect(calls[0].init?.method).toBe("POST");
    const body = calls[0].init?.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("file")).toBe(file);
  });

  it("pastes text as JSON with source_type brand_doc", async () => {
    const { result } = renderHook(() => usePasteDocument("c1"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ title: "Voice", text: "We are playful." });
    });
    expect(calls[0].path).toBe("/clients/c1/documents");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(calls[0].init?.body as string)).toEqual({
      title: "Voice",
      text: "We are playful.",
      source_type: "brand_doc",
    });
  });

  it("re-indexes with a POST", async () => {
    const { result } = renderHook(() => useReindexDocument("c1"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync("d1");
    });
    expect(calls[0].path).toBe("/documents/d1/reindex");
    expect(calls[0].init?.method).toBe("POST");
  });

  it("deletes with a DELETE", async () => {
    const { result } = renderHook(() => useDeleteDocument("c1"), { wrapper });
    await act(async () => {
      await result.current.mutateAsync("d1");
    });
    expect(calls[0].path).toBe("/documents/d1");
    expect(calls[0].init?.method).toBe("DELETE");
  });
});
