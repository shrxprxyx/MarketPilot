import { isActive, navFor } from "@/lib/nav";

const labels = (role: Parameters<typeof navFor>[0]) =>
  navFor(role).flatMap((s) => s.items.map((i) => i.label));

describe("navFor", () => {
  it("shows a member only Dashboard and Clients", () => {
    expect(labels("member")).toEqual(["Dashboard", "Clients"]);
  });

  it("omits the AI section entirely for a member", () => {
    expect(navFor("member").map((s) => s.label)).toEqual(["A · WORKSPACE"]);
  });

  it("adds AI models and Usage for a manager, but not Team", () => {
    expect(labels("manager")).toEqual(["Dashboard", "Clients", "AI models", "Usage"]);
  });

  it("shows an admin everything", () => {
    expect(labels("admin")).toEqual(["Dashboard", "Clients", "Team", "AI models", "Usage"]);
    expect(navFor("admin").map((s) => s.label)).toEqual(["A · WORKSPACE", "B · AI"]);
  });

  it("numbers items continuously across sections", () => {
    const numbers = navFor("admin").flatMap((s) => s.items.map((i) => i.number));
    expect(numbers).toEqual(["01", "02", "03", "04", "05"]);
  });

  it("numbers a manager's items 01 to 04 with no gap", () => {
    const numbers = navFor("manager").flatMap((s) => s.items.map((i) => i.number));
    expect(numbers).toEqual(["01", "02", "03", "04"]);
  });
});

describe("isActive", () => {
  it("matches the dashboard only on the exact root path", () => {
    expect(isActive("/", "/")).toBe(true);
    expect(isActive("/", "/clients")).toBe(false);
  });

  it("matches nested routes under an item", () => {
    expect(isActive("/clients", "/clients")).toBe(true);
    expect(isActive("/clients", "/clients/123")).toBe(true);
  });

  it("does not match a sibling that merely shares a prefix", () => {
    expect(isActive("/clients", "/clients-archive")).toBe(false);
  });
});
