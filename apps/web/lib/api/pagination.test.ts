import { fetchAllPages } from "@/lib/api/pagination";

const paths: string[] = [];
const pages: Record<string, { items: string[]; next_cursor: string | null }> = {
  "/things?limit=100": { items: ["a", "b"], next_cursor: "c 1" },
  "/things?limit=100&cursor=c%201": { items: ["c"], next_cursor: null },
};
vi.mock("@/lib/api/client", () => ({
  apiFetch: async (path: string) => {
    paths.push(path);
    return pages[path];
  },
}));

describe("fetchAllPages", () => {
  it("follows next_cursor until the list ends and joins the pages", async () => {
    expect(await fetchAllPages<string>("/things")).toEqual(["a", "b", "c"]);
    expect(paths).toEqual(["/things?limit=100", "/things?limit=100&cursor=c%201"]);
  });
});
