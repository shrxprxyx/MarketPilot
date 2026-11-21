import { expect, test } from "@playwright/test";
import { registerAgency } from "./helpers";
import { startStubLlm, STUB_PLAN } from "./stub-llm";

test("strategy runs on the tenant's own model with sources and cost", async ({ page }) => {
  const stub = await startStubLlm();
  try {
    await registerAgency(page, "strategy");

    // 1. Connect a model (an OpenAI-compatible stub) and route the strategy task to it.
    await page.goto("/settings/ai");
    const main = page.locator("main");
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

    // 2. A client with an indexed knowledge document.
    await page.goto("/clients");
    await page.getByRole("button", { name: "New client" }).click();
    await page.getByLabel("Name").fill("Brew Co");
    await page.getByLabel("Industry (optional)").fill("Specialty coffee");
    await page.getByRole("button", { name: "Create client" }).click();
    await expect(page.getByRole("heading", { name: "Brew Co" })).toBeVisible();
    const panel = page.getByRole("tabpanel");

    // Strategy with no knowledge yet: still generates, and says no documents were used.
    await page.getByRole("tab", { name: "Strategy" }).click();
    await expect(panel.getByText("No strategies yet")).toBeVisible();
    await panel.getByRole("button", { name: "Generate strategy" }).click();
    await expect(panel.getByText(STUB_PLAN.summary)).toBeVisible();
    await expect(panel.getByText("No knowledge documents were used")).toBeVisible();

    // Add knowledge and wait for the worker to index it.
    await page.getByRole("tab", { name: "Knowledge" }).click();
    await page.getByLabel("Title").fill("Roasting notes");
    await page.getByLabel("Text", { exact: true }).fill(
      "Brew Co roasts specialty coffee in small batches and ships fresh beans within two days.",
    );
    await page.getByRole("button", { name: "Add text" }).click();
    await expect(panel.getByText("Ready")).toHaveCount(1, { timeout: 30_000 });

    // 3. Regenerate: a new version, with the document as a source and tokens from the model.
    await page.getByRole("tab", { name: "Strategy" }).click();
    await panel.getByRole("button", { name: "Regenerate" }).click();
    const month = await page.getByLabel("Month").inputValue();
    await expect(page.getByRole("button", { name: `${month} · v2` })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const sources = panel.getByRole("region", { name: "Sources used" });
    await expect(sources.getByText("Roasting notes")).toBeVisible();
    await expect(sources.getByText(/ships fresh beans/)).toBeVisible();
    await expect(panel.getByText("stub-model", { exact: true })).toBeVisible();
    await expect(panel.getByText(/321 in/)).toBeVisible();
    await expect(panel.getByText(/123 out/)).toBeVisible();
    await expect(panel.getByText("Cost unknown", { exact: true })).toBeVisible(); // unpriced, not $0
    // The pre-flight estimate line is also shown, and says the same for an unpriced model.
    await expect(panel.getByText(/^Cost unknown for this model · about [\d,]+ tokens in$/)).toBeVisible();
    await page.screenshot({ path: "test-results/shots/strategy.png", fullPage: true });

    // The model really received the brand's knowledge and the client facts in its prompt.
    const last = stub.requests.at(-1)!;
    const prompt = last.messages.map((m) => m.content).join("\n");
    expect(prompt).toContain("Specialty coffee");
    expect(prompt).toContain("ships fresh beans within two days");
    expect(prompt).toContain(month);

    // The earlier version is still there and switchable.
    await page.getByRole("button", { name: `${month} · v1` }).click();
    await expect(panel.getByText("No knowledge documents were used")).toBeVisible();

    // A reload keeps both versions (stored, not just in memory).
    await page.reload();
    await page.getByRole("tab", { name: "Strategy" }).click();
    await expect(page.getByRole("button", { name: `${month} · v2` })).toBeVisible();

    // 4. Usage recorded the calls under the strategy task.
    await page.goto("/usage");
    await expect(page.getByRole("rowheader", { name: "strategy" }).first()).toBeVisible();
    await expect(page.getByRole("rowheader", { name: "stub-model" }).first()).toBeVisible();
  } finally {
    await stub.close();
  }
});
