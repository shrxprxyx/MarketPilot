import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { registerAgency } from "./helpers";

// WCAG 2.1 A and AA rules (SRS NFR-06). Any violation fails the test and lists what to fix.
async function expectNoViolations(page: Page, name: string) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const summary = results.violations.map(
    (v) =>
      `${v.id} (${v.impact}): ${v.help}\n` +
      v.nodes.map((n) => `    ${n.target.join(" ")}`).join("\n"),
  );
  expect(summary, `${name} has accessibility violations`).toEqual([]);
}

test("signed-out pages have no accessibility violations", async ({ page }) => {
  for (const path of ["/login", "/register"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectNoViolations(page, path);
  }
});

test("signed-in pages have no accessibility violations", async ({ page }) => {
  await registerAgency(page, "a11y");

  const pages: [string, string][] = [
    ["/", "Agency overview"],
    ["/clients", "The businesses you run marketing for, with their knowledge documents."],
    ["/settings/ai", "Connect your own AI models and choose which one handles each task."],
    ["/usage", "Usage"],
    ["/team", "Team"],
    ["/settings/agency", "Your agency's name and the branding used on client-facing reports."],
  ];
  for (const [path, marker] of pages) {
    await page.goto(path);
    await expect(page.locator("main").getByText(marker).first()).toBeVisible();
    // let the data requests settle so skeletons are not what gets scanned
    await page.waitForLoadState("networkidle");
    await expectNoViolations(page, path);
  }

  // A modal dialog is its own accessibility surface.
  await page.goto("/clients");
  await page.getByRole("button", { name: "New client" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expectNoViolations(page, "the New client dialog");
});
