import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

export const STUB_PLAN = {
  summary: "Grow newsletter subscriptions through local SEO and email.",
  objectives: [
    { title: "More subscribers", kpis: [{ name: "New subscribers", target: "200" }] },
  ],
  channels: [{ name: "Email", rationale: "Highest retention." }],
  risks: [{ risk: "Supply delays", mitigation: "Buffer stock." }],
};

export const STUB_USAGE = { prompt_tokens: 321, completion_tokens: 123 };

/**
 * A tiny OpenAI-compatible server so strategy generation runs through the real gateway
 * and provider adapter without a real key. `requests` collects every chat request body.
 */
export async function startStubLlm(): Promise<{
  baseUrl: string;
  requests: { messages: { role: string; content: string }[] }[];
  close: () => Promise<void>;
}> {
  const requests: { messages: { role: string; content: string }[] }[] = [];
  const server: Server = createServer((req, res) => {
    let raw = "";
    req.on("data", (c) => (raw += c));
    req.on("end", () => {
      res.setHeader("content-type", "application/json");
      if (req.method === "POST" && req.url === "/v1/chat/completions") {
        requests.push(JSON.parse(raw));
        res.end(
          JSON.stringify({
            choices: [{ message: { content: JSON.stringify(STUB_PLAN) } }],
            usage: STUB_USAGE,
          }),
        );
      } else if (req.method === "GET" && req.url === "/v1/models") {
        res.end(JSON.stringify({ data: [{ id: "stub-model" }] }));
      } else {
        res.statusCode = 404;
        res.end("{}");
      }
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    baseUrl: `http://127.0.0.1:${port}/v1`,
    requests,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}
