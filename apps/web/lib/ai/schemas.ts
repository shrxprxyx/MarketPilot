import { z } from "zod";

export const PROVIDERS = ["openai", "anthropic", "ollama", "openai_compatible"] as const;
export type Provider = (typeof PROVIDERS)[number];

export const TASKS = ["strategy", "content", "analysis"] as const;
export type TaskType = (typeof TASKS)[number];

// Mirrors the API's rules (apps/api/app/api/v1/ai_connections.py and ai_routes.py).
// Form inputs yield "" for untouched fields, so "" counts as absent.
export const connectionSchema = z
  .object({
    provider: z.enum(PROVIDERS),
    label: z.string().trim().min(1, "Name is required").max(120, "Name is too long"),
    base_url: z.string().trim().max(500).optional(),
    api_key: z.string().max(500).optional(),
  })
  .superRefine((v, ctx) => {
    const needsUrl = v.provider === "ollama" || v.provider === "openai_compatible";
    if (needsUrl && !v.base_url) {
      ctx.addIssue({ code: "custom", path: ["base_url"], message: "Base URL is required for this provider" });
    }
    // Anthropic has no base URL field, so a stale value from another provider is ignored.
    if (v.provider !== "anthropic" && v.base_url && !/^https?:\/\//.test(v.base_url)) {
      ctx.addIssue({ code: "custom", path: ["base_url"], message: "Base URL must start with http:// or https://" });
    }
    if (v.provider !== "ollama") {
      if (!v.api_key) {
        ctx.addIssue({ code: "custom", path: ["api_key"], message: "API key is required for this provider" });
      } else if (v.api_key.length < 4) {
        ctx.addIssue({ code: "custom", path: ["api_key"], message: "API key must be at least 4 characters" });
      }
    }
  });
export type ConnectionValues = z.infer<typeof connectionSchema>;

export const routeSchema = z
  .object({
    task_type: z.enum(TASKS),
    connection_id: z.string().min(1, "Choose a connection"),
    model: z.string().trim().min(1, "Model is required").max(200),
    temperature: z.number("Enter a number").min(0, "Minimum is 0").max(2, "Maximum is 2"),
    max_tokens: z
      .number("Enter a number")
      .int("Whole numbers only")
      .min(1, "Minimum is 1")
      .max(200_000, "Maximum is 200000"),
    fallback_connection_id: z.string().optional(),
    fallback_model: z.string().trim().max(200).optional(),
  })
  .superRefine((v, ctx) => {
    if (!v.fallback_connection_id !== !v.fallback_model) {
      ctx.addIssue({
        code: "custom",
        path: ["fallback_model"],
        message: "Set both a fallback connection and model, or neither",
      });
    }
  });
export type RouteValues = z.infer<typeof routeSchema>;
