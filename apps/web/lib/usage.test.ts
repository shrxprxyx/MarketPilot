import { fillDays, formatCost, formatTokens, totals } from "@/lib/usage";
import type { UsageRow } from "@/lib/queries/ai";

const row = (over: Partial<UsageRow> = {}): UsageRow => ({
  key: "k",
  calls: 1,
  tokens_in: 10,
  tokens_out: 5,
  cost_usd: "0.5",
  unpriced_calls: 0,
  ...over,
});

describe("totals", () => {
  it("sums every field and converts cost to a number", () => {
    const t = totals([
      row({ calls: 2, tokens_in: 100, tokens_out: 50, cost_usd: "1.25", unpriced_calls: 1 }),
      row({ calls: 3, tokens_in: 20, tokens_out: 10, cost_usd: "0.75", unpriced_calls: 2 }),
    ]);
    expect(t).toEqual({ calls: 5, tokensIn: 120, tokensOut: 60, cost: 2, unpriced: 3 });
  });

  it("returns zeros for no rows", () => {
    expect(totals([])).toEqual({ calls: 0, tokensIn: 0, tokensOut: 0, cost: 0, unpriced: 0 });
  });
});

describe("formatCost", () => {
  it("never shows a sub-cent cost as $0.00", () => {
    expect(formatCost("0.000123")).toBe("$0.0001");
  });
  it("uses 4 decimals under $1 and 2 from $1 up", () => {
    expect(formatCost("0.5")).toBe("$0.5000");
    expect(formatCost("12.5")).toBe("$12.50");
  });
  it("shows exact zero as $0.00", () => {
    expect(formatCost(0)).toBe("$0.00");
  });
});

describe("formatTokens", () => {
  it("formats plain, thousands and millions", () => {
    expect(formatTokens(0)).toBe("0");
    expect(formatTokens(1234)).toBe("1,234");
    expect(formatTokens(12_500)).toBe("12.5K");
    expect(formatTokens(1_250_000)).toBe("1.25M");
  });
});

describe("fillDays", () => {
  it("returns exactly N days, oldest first, with gaps zeroed", () => {
    const today = new Date("2026-11-21T10:00:00Z");
    const real = row({ key: "2026-11-20", calls: 4, tokens_in: 40, tokens_out: 20, cost_usd: "2" });
    const out = fillDays([real], 3, today);
    expect(out.map((r) => r.key)).toEqual(["2026-11-19", "2026-11-20", "2026-11-21"]);
    expect(out[1]).toEqual(real);
    expect(out[0]).toEqual({
      key: "2026-11-19",
      calls: 0,
      tokens_in: 0,
      tokens_out: 0,
      cost_usd: "0",
      unpriced_calls: 0,
    });
  });
});
