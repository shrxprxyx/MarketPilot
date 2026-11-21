import { connectionSchema, routeSchema } from "@/lib/ai/schemas";

const route = {
  task_type: "strategy" as const,
  connection_id: "c1",
  model: "gpt-4o",
  temperature: 0.7,
  max_tokens: 2048,
};

describe("connectionSchema", () => {
  it("rejects ollama without a base URL", () => {
    const r = connectionSchema.safeParse({ provider: "ollama", label: "Local" });
    expect(r.success).toBe(false);
  });

  it("rejects openai_compatible without a base URL", () => {
    const r = connectionSchema.safeParse({ provider: "openai_compatible", label: "X", api_key: "sk-1234" });
    expect(r.success).toBe(false);
  });

  it("rejects openai without an API key", () => {
    expect(connectionSchema.safeParse({ provider: "openai", label: "X" }).success).toBe(false);
  });

  it("rejects an API key shorter than 4 characters", () => {
    expect(connectionSchema.safeParse({ provider: "openai", label: "X", api_key: "abc" }).success).toBe(false);
  });

  it("rejects a non-http base URL", () => {
    const r = connectionSchema.safeParse({ provider: "ollama", label: "X", base_url: "ftp://x" });
    expect(r.success).toBe(false);
  });

  it("accepts ollama with a base URL and no key", () => {
    const r = connectionSchema.safeParse({ provider: "ollama", label: "X", base_url: "https://tunnel.example" });
    expect(r.success).toBe(true);
  });

  it("ignores a base URL for anthropic, which does not use one", () => {
    const r = connectionSchema.safeParse({ provider: "anthropic", label: "X", api_key: "sk-1234", base_url: "abc" });
    expect(r.success).toBe(true);
  });

  it("accepts openai with a key and no URL", () => {
    expect(connectionSchema.safeParse({ provider: "openai", label: "X", api_key: "sk-1234" }).success).toBe(true);
  });
});

describe("routeSchema", () => {
  it("rejects temperature above 2", () => {
    expect(routeSchema.safeParse({ ...route, temperature: 2.5 }).success).toBe(false);
  });

  it("rejects max_tokens of 0", () => {
    expect(routeSchema.safeParse({ ...route, max_tokens: 0 }).success).toBe(false);
  });

  it("rejects a fallback connection without a fallback model", () => {
    expect(routeSchema.safeParse({ ...route, fallback_connection_id: "c2" }).success).toBe(false);
  });

  it("rejects a fallback model without a fallback connection", () => {
    expect(routeSchema.safeParse({ ...route, fallback_model: "m" }).success).toBe(false);
  });

  it("accepts no fallback and a complete fallback pair", () => {
    expect(routeSchema.safeParse(route).success).toBe(true);
    expect(
      routeSchema.safeParse({ ...route, fallback_connection_id: "c2", fallback_model: "m" }).success,
    ).toBe(true);
  });
});
