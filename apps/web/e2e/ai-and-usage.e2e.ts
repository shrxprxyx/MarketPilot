import { expect, test } from "@playwright/test";
import { registerAgency, sql } from "./helpers";

test("AI models and usage", async ({ page }) => {
  const { agency } = await registerAgency(page, "ai");
  const panel = page.locator("main");

  // --- AI models: add a connection, a failed Test shows the error inline, routing persists ---
  await page.goto("/settings/ai");
  await expect(panel.getByText(/no connections yet/i)).toBeVisible();
  await panel.getByRole("button", { name: "Add connection" }).click();
  await page.getByLabel("Provider").selectOption("ollama");
  await expect(page.getByLabel("API key")).toHaveCount(0);
  await expect(page.getByText(/tunnel/i)).toBeVisible();
  await page.getByLabel("Name").fill("Local Ollama");
  await page.getByRole("button", { name: "Save connection" }).click();
  await expect(page.getByText("Base URL is required for this provider")).toBeVisible();
  await page.getByLabel("Base URL").fill("http://127.0.0.1:9/");
  await page.getByRole("button", { name: "Save connection" }).click();
  await expect(panel.locator("li p", { hasText: "Local Ollama" })).toBeVisible();

  await panel.getByRole("button", { name: "Test Local Ollama" }).click();
  await expect(panel.getByRole("alert")).toBeVisible(); // nothing listens on :9 -> inline error
  await page.screenshot({ path: "test-results/shots/ai-connections.png", fullPage: true });

  await page.getByLabel("strategy connection").selectOption({ label: "Local Ollama" });
  await page.getByLabel("strategy model").fill("llama3");
  await page.getByLabel("strategy temperature").fill("2.5");
  await page.getByRole("button", { name: "Save routing" }).click();
  await expect(page.getByText("Maximum is 2")).toBeVisible();
  await page.getByLabel("strategy temperature").fill("0.7");
  await page.getByRole("button", { name: "Save routing" }).click();
  await expect(page.getByRole("button", { name: "Save routing" })).toBeDisabled();
  await page.reload();
  await expect(page.getByLabel("strategy model")).toHaveValue("llama3");

  // --- Usage: empty state first, then seeded rows ---
  await page.goto("/usage");
  await expect(page.getByText("No AI calls yet")).toBeVisible();

  const tenantId = sql(`SELECT id FROM tenants WHERE name = '${agency}'`);
  expect(tenantId).toMatch(/^[0-9a-f-]{36}$/);
  const row = (task: string, model: string, tin: number, tout: number, cost: string, ago: number) =>
    `(gen_random_uuid(),'${tenantId}','openai','${task}','${model}',${tin},${tout},${cost},500,` +
    `now() - interval '${ago} days', now())`;
  sql(
    `INSERT INTO usage_logs (id,tenant_id,provider,task_type,model,tokens_in,tokens_out,cost_usd,latency_ms,created_at,updated_at) VALUES ` +
      [
        row("strategy", "gpt-4o", 12000, 3000, "0.0450", 0),
        row("content", "gpt-4o", 5000, 2500, "0.0300", 1),
        row("content", "gpt-4o-mini", 8000, 4000, "0.0021", 2),
        row("analysis", "llama3", 3000, 900, "NULL", 3),
        row("strategy", "gpt-4o", 9000, 2000, "0.0310", 6),
      ].join(","),
  );

  await page.reload();
  await expect(page.getByRole("img", { name: /Daily cost over 30 days/ })).toBeVisible();
  await expect(page.getByText("1 call unpriced").first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "By task" })).toBeVisible();
  await expect(page.getByRole("rowheader", { name: "gpt-4o-mini" })).toBeVisible();
  await page.screenshot({ path: "test-results/shots/usage-30d.png", fullPage: true });

  await page.getByRole("button", { name: "7 days" }).click();
  await expect(page.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("img", { name: /Daily cost over 7 days/ })).toBeVisible();
  await page.screenshot({ path: "test-results/shots/usage-7d.png", fullPage: true });

  // Hovering a bar updates the readout.
  await page.locator("[data-bar]").nth(5).hover();
  await expect(page.locator("[aria-live=polite]").first()).toBeVisible();
});
