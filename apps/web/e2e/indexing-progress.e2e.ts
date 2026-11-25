import { expect, test } from "@playwright/test";
import { registerAgency } from "./helpers";

// Needs the Celery worker. The text is large (hundreds of passages) so that indexing lasts long
// enough to watch: this proves progress reaches the browser live, through the Next.js proxy.
test("indexing progress streams to the knowledge tab", async ({ page }) => {
  // Embedding the text is CPU-bound and took 14 to 47 s across runs; the dev server's first-visit
  // compiles add about 30 s of setup. The shared 90 s limit left almost no margin.
  test.setTimeout(180_000);
  await registerAgency(page, "progress");
  await page.goto("/clients");
  await page.getByRole("button", { name: "New client" }).first().click();
  await page.getByRole("dialog").getByLabel("Name", { exact: true }).fill("Progress Co");
  await page.getByRole("button", { name: "Create client" }).click();
  await page.getByRole("tab", { name: "Knowledge" }).click();

  const body = Array.from(
    { length: 2500 },
    (_, i) => `Paragraph ${i}: our roastery ships fresh coffee to subscriber number ${i * 7}.`,
  ).join("\n\n");

  const stream = page.waitForResponse((r) => /\/api\/jobs\/[^/]+\/events\?ticket=/.test(r.url()));
  await page.getByLabel("Title").fill("Big handbook");
  await page.getByLabel("Text", { exact: true }).fill(body);
  await page.getByRole("button", { name: "Add text" }).click();

  const response = await stream;
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("text/event-stream");

  // The bar only renders once an event has actually arrived over the stream.
  const bar = page.getByRole("progressbar", { name: "Indexing Big handbook" });
  await expect(bar).toBeVisible();

  const row = page.getByRole("tabpanel").getByRole("listitem").filter({ hasText: "Big handbook" });
  await expect(row.getByText("Ready", { exact: true })).toBeVisible({ timeout: 150_000 });
  await expect(bar).toHaveCount(0);
});
