import { safeNext } from "@/lib/auth/safe-next";

describe("safeNext", () => {
  it("keeps a same-origin relative path", () => {
    expect(safeNext("/clients")).toBe("/clients");
    expect(safeNext("/clients?tab=brand")).toBe("/clients?tab=brand");
  });

  it.each([
    ["protocol-relative URL", "//evil.com"],
    ["absolute URL", "https://evil.com"],
    ["backslash trick", "/\\evil.com"],
    ["no leading slash", "clients"],
    ["empty string", ""],
    ["null", null],
    ["undefined", undefined],
  ])("falls back to / for %s", (_label, value) => {
    expect(safeNext(value)).toBe("/");
  });
});
