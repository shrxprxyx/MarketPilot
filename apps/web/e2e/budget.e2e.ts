import { expect, test } from "@playwright/test";
import { registerAgency, sql } from "./helpers";
import { startStubLlm, STUB_PLAN } from "./stub-llm";

test("budget: warning, hard stop, server-side enforcement and recovery", async ({ page }) => {
  test.setTimeout(180_000); // many page loads; the dev server compiles each route on first visit
  const stub = await startStubLlm();
  try {
    const { agency } = await registerAgency(page, "budget");
    const main = page.locator("main");
    const panel = page.getByRole("tabpanel");
    const bar = page.getByRole("progressbar", { name: "Monthly AI budget used" });

    // Setup: a routed (unpriced) stub model and a client.
    await page.goto("/settings/ai");
    await main.getByRole("button", { name: "Add connection" }).click();
    await page.getByLabel("Provider").selectOption("openai_compatible");
    await page.getByLabel("Name").fill("Stub model");
    await page.getByLabel("Base URL").fill(stub.baseUrl);
    await page.getByLabel("API key").fill("sk-stub-key-1234");
    await page.getByRole("button", { name: "Save connection" }).click();
    await expect(main.locator("li p", { hasText: "Stub model" })).toBeVisible();
    await page.getByLabel("strategy connection").selectOption({ label: "Stub model" });
    await page.getByLabel("strategy model").fill("stub-model");
    await page.getByRole("button", { name: "Save routing" }).click();
    await expect(page.getByRole("button", { name: "Save routing" })).toBeDisabled();

    await page.goto("/clients");
    await page.getByRole("button", { name: "New client" }).click();
    await page.getByLabel("Name").fill("Budget Client");
    await page.getByRole("button", { name: "Create client" }).click();
    await expect(page.getByRole("heading", { name: "Budget Client" })).toBeVisible();
    const clientUrl = page.url();

    // Spend so far this month: $0.17 (seeded straight into usage_logs).
    const tenantId = sql(`SELECT id FROM tenants WHERE name = '${agency}'`);
    expect(tenantId).toMatch(/^[0-9a-f-]{36}$/);
    sql(
      `INSERT INTO usage_logs (id,tenant_id,provider,task_type,model,tokens_in,tokens_out,cost_usd,latency_ms,created_at,updated_at) ` +
        `VALUES (gen_random_uuid(),'${tenantId}','openai','strategy','gpt-4o',1000,500,0.17,400,now(),now())`,
    );

    const setBudget = async (amount: string, hardStop: boolean) => {
      await page.goto("/settings/ai");
      await page.getByLabel("Monthly budget (USD)").fill(amount);
      const box = page.getByLabel(/stop AI calls when the budget is reached/i);
      if ((await box.isChecked()) !== hardStop) await box.click();
      await page.getByRole("button", { name: "Save budget" }).click();
      await expect(page.getByRole("button", { name: "Save budget" })).toBeDisabled();
    };
    const openStrategy = async () => {
      await page.goto(clientUrl);
      await page.getByRole("tab", { name: "Strategy" }).click();
    };
    const generate = panel.getByRole("button", { name: /^(Generate strategy|Regenerate)$/ });

    // 1. Budget equals spend with a hard stop: Generate is blocked, with an explanation.
    await setBudget("0.17", true);
    await expect(main.getByText("Budget reached", { exact: true })).toBeVisible();
    await page.screenshot({ path: "test-results/shots/budget-settings.png", fullPage: true });
    await openStrategy();
    await expect(panel.getByText("Budget reached", { exact: true })).toBeVisible();
    await expect(panel.getByText(/monthly budget reached/i)).toBeVisible();
    await expect(generate).toBeDisabled();
    await expect(panel.getByText(/AI generation is paused/)).toBeVisible();
    await page.screenshot({ path: "test-results/shots/budget-blocked.png", fullPage: true });
    await page.goto("/usage");
    await expect(bar).toBeVisible();
    await expect(page.getByText("Budget reached", { exact: true })).toBeVisible();

    // 2. The same budget without a hard stop is only a warning: generation still works.
    await setBudget("0.17", false);
    await openStrategy();
    await expect(panel.getByText("Budget reached", { exact: true })).toBeVisible();
    await expect(generate).toBeEnabled();
    await expect(panel.getByText(/Cost unknown for this model · about [\d,]+ tokens in/)).toBeVisible();
    await generate.click();
    await expect(panel.getByText(STUB_PLAN.summary)).toBeVisible();
    expect(stub.requests).toHaveLength(1);

    // 3. 85% used (spend 0.17 of 0.20) with a hard stop: an in-words warning, still allowed.
    await setBudget("0.20", true);
    await openStrategy();
    await expect(panel.getByText("85% of budget used")).toBeVisible();
    await expect(bar).toHaveAttribute("aria-valuenow", "85");
    await expect(generate).toBeEnabled();
    await page.screenshot({ path: "test-results/shots/budget-warning.png", fullPage: true });

    // 4. The budget is lowered behind the open page's back. The UI still thinks it can
    //    generate, so the server itself must refuse: 402, no model call, no new usage row.
    sql(`UPDATE tenants SET monthly_budget_usd = 0.17, hard_stop = true WHERE id = '${tenantId}'`);
    const rowsBefore = sql(`SELECT count(*) FROM usage_logs WHERE tenant_id = '${tenantId}'`);
    await generate.click();
    await expect(panel.getByRole("alert")).toContainText("Monthly AI budget reached");
    expect(stub.requests).toHaveLength(1);
    expect(sql(`SELECT count(*) FROM usage_logs WHERE tenant_id = '${tenantId}'`)).toBe(rowsBefore);

    // 5. Raising the budget restores the budget check, but a hard stop cannot be enforced for
    //    a model with no known price (its spend is never counted), so the server refuses
    //    that too: 409, no model call, no new usage row.
    await setBudget("5", true);
    await openStrategy();
    await expect(generate).toBeEnabled();
    await expect(panel.getByText("3% used")).toBeVisible();
    await generate.click();
    await expect(panel.getByRole("alert")).toContainText("no known price");
    expect(stub.requests).toHaveLength(1);
    expect(sql(`SELECT count(*) FROM usage_logs WHERE tenant_id = '${tenantId}'`)).toBe(rowsBefore);

    // Once the model has a price the same request goes through and its cost is recorded.
    sql(
      `INSERT INTO model_pricing (id,provider,model,input_per_mtok,output_per_mtok) ` +
        `VALUES (gen_random_uuid(),'openai_compatible','stub-model',1,1) ON CONFLICT DO NOTHING`,
    );
    await generate.click();
    await expect(panel.getByRole("button", { name: /v2$/ })).toBeVisible();
    expect(stub.requests).toHaveLength(2);

    await page.goto("/settings/ai");
    await page.getByLabel("Monthly budget (USD)").fill("");
    await page.getByRole("button", { name: "Save budget" }).click();
    await expect(page.getByRole("button", { name: "Save budget" })).toBeDisabled();
    await page.reload();
    await expect(page.getByLabel("Monthly budget (USD)")).toHaveValue("");
    await expect(bar).toHaveCount(0);
  } finally {
    sql(`DELETE FROM model_pricing WHERE provider = 'openai_compatible' AND model = 'stub-model'`);
    await stub.close();
  }
});
